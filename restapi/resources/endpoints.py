# -*- coding: utf-8 -*-

"""
Base endpoints: authorization, status, checks.
And a Farm: How to create endpoints into REST service.
"""

import pytz
import jwt
import os

from datetime import datetime, timedelta
from flask import jsonify, current_app

from restapi import decorators as decorate
from restapi.exceptions import RestApiException
from restapi.rest.definition import EndpointResource
# from restapi.services.authentication import BaseAuthentication
from restapi.services.detect import detector
from restapi.services.mail import send_mail, send_mail_is_active
from restapi.services.mail import get_html_template
from utilities import htmlcodes as hcodes
from utilities.time import timestamp_from_string
from utilities.globals import mem
from restapi.confs import PRODUCTION
from utilities.logs import get_logger

from restapi.flask_ext.flask_auth import HandleSecurity

log = get_logger(__name__)


class Status(EndpointResource):
    """ API online client testing """

    # @decorate.catch_error()
    def get(self):

        #####################
        # DEBUG
        # print(self.auth)
        # log.pp({'test': 1})
        # log.pp(pytz)
        # return {'Hello', 'World!'}

        #####################
        # TEST ERRORS
        # return self.send_errors(message='test error')

        #####################
        # NORMAL RESPONSE
        return 'Server is alive!'

        #####################
        # MAIL TEST BLOCK

        # # Import smtplib for the actual sending function
        # import smtplib

        # # Import the email modules we'll need
        # from email.mime.text import MIMEText

        # msg = MIMEText("just a simple test")

        # # me == the sender's email address
        # # you == the recipient's email address
        # msg['Subject'] = 'Test email'
        # msg['From'] = "m.dantonio@cineca.it"
        # msg['To'] = "m.dantonio@cineca.it"

        # # Send the message via our own SMTP server.
        # s = smtplib.SMTP('smtp.dockerized.io')
        # s.send_message(msg)
        # s.quit()


class SwaggerSpecifications(EndpointResource):
    """
    Specifications output throught Swagger (open API) standards
    """

    def get(self):

        # NOTE: swagger dictionary is read only once, at server init time
        swagjson = mem.customizer._definitions

        # NOTE: changing dinamically options, based on where the client lies
        from restapi.confs import PRODUCTION
        from flask import request
        from utilities.helpers import get_api_url
        api_url = get_api_url(request, PRODUCTION)
        scheme, host = api_url.rstrip('/').split('://')
        swagjson['host'] = host
        swagjson['schemes'] = [scheme]

        # Jsonify, so we skip custom response building
        return jsonify(swagjson)


class Login(EndpointResource):
    """ Let a user login with the developer chosen method """

    def verify_information(
            self, user, security, totp_auth, totp_code, now=None):

        message_body = {}
        message_body['actions'] = []
        error_message = None

        if totp_auth and totp_code is None:
            message_body['actions'].append(
                self.auth.SECOND_FACTOR_AUTHENTICATION)
            error_message = "You do not provided a valid second factor"

        epoch = datetime.fromtimestamp(0, pytz.utc)
        last_pwd_change = user.last_password_change
        if last_pwd_change is None or last_pwd_change == 0:
            last_pwd_change = epoch

        if self.auth.FORCE_FIRST_PASSWORD_CHANGE and last_pwd_change == epoch:

            message_body['actions'].append('FIRST LOGIN')
            error_message = "Please change your temporary password"

            if totp_auth:

                qr_code = security.get_qrcode(user)

                message_body["qr_code"] = qr_code

        elif self.auth.MAX_PASSWORD_VALIDITY > 0:

            if last_pwd_change == epoch:
                expired = True
            else:
                valid_until = \
                    last_pwd_change + timedelta(
                        days=self.auth.MAX_PASSWORD_VALIDITY)

                if now is None:
                    now = datetime.now(pytz.utc)
                expired = (valid_until < now)

            if expired:

                message_body['actions'].append('PASSWORD EXPIRED')
                error_message = "Your password is expired, please change it"

        if error_message is None:
            return None

        return self.force_response(
            message_body, errors=error_message, code=hcodes.HTTP_BAD_FORBIDDEN)

    @decorate.catch_error()
    def post(self):

        # ########## INIT ##########
        jargs = self.get_input()
        username = jargs.get('username')
        if username is None:
            username = jargs.get('email')
        username = username.lower()

        password = jargs.get('password')
        if password is None:
            password = jargs.get('pwd')

        # ##################################################
        # Now credentials are checked at every request
        if username is None or password is None:
            msg = "Missing username or password"
            raise RestApiException(
                msg, status_code=hcodes.HTTP_BAD_UNAUTHORIZED)

        now = datetime.now(pytz.utc)

        new_password = jargs.get('new_password')
        password_confirm = jargs.get('password_confirm')

        totp_authentication = (
            self.auth.SECOND_FACTOR_AUTHENTICATION is not None and
            self.auth.SECOND_FACTOR_AUTHENTICATION == self.auth.TOTP
        )

        if totp_authentication:
            totp_code = jargs.get('totp_code')
        else:
            totp_code = None

        security = HandleSecurity(self.auth)
        # ##################################################
        # Authentication control
        security.verify_blocked_username(username)
        token, jti = self.auth.make_login(username, password)
        security.verify_token(username, token)
        user = self.auth.get_user()
        security.verify_blocked_user(user)

        if totp_authentication and totp_code is not None:
            security.verify_totp(user, totp_code)

        # ##################################################
        # If requested, change the password
        if new_password is not None and password_confirm is not None:

            pwd_changed = security.change_password(
                user, password, new_password, password_confirm)

            if pwd_changed:
                password = new_password
                token, jti = self.auth.make_login(username, password)

        # ##################################################
        # Something is missing in the authentication, asking action to user
        ret = self.verify_information(
            user, security, totp_authentication, totp_code, now)
        if ret is not None:
            return ret

        # ##################################################
        # Everything is ok, let's save authentication information

        if user.first_login is None:
            user.first_login = now
        user.last_login = now
        # Should be saved inside save_token...
        # user.save()
        self.auth.save_token(self.auth._user, token, jti)

        # FIXME: split response as above in access_token and token_type?
        # # The right response should be the following
        # {
        #   "scope": "https://b2stage-test.cineca.it/api/.*",
        #   "access_token": "EEwJ6tF9x5WCIZDYzyZGaz6Khbw7raYRIBV_WxVvgmsG",
        #   "token_type": "Bearer",
        #   "user": "pippo",
        #   "expires_in": 28800
        # }
        # FIXME: also set headers in a standard way if it exists

        return {'token': token}


class Logout(EndpointResource):
    """ Let the logged user escape from here, invalidating current token """

    def get(self):
        self.auth.invalidate_token(token=self.auth.get_token())
        return self.empty_response()


class RecoverPassword(EndpointResource):

    @decorate.catch_error()
    def post(self):

        if not send_mail_is_active():
            raise RestApiException(
                'Server misconfiguration, unable to reset password. ' +
                'Please report this error to adminstrators',
                status_code=hcodes.HTTP_BAD_REQUEST)

        reset_email = self.get_input(single_parameter='reset_email')

        if reset_email is None:
            raise RestApiException(
                'Invalid reset email',
                status_code=hcodes.HTTP_BAD_FORBIDDEN)

        reset_email = reset_email.lower()

        user = self.auth.get_user_object(username=reset_email)

        if user is None:
            raise RestApiException(
                'Sorry, %s ' % reset_email +
                'is not recognized as a valid username or email address',
                status_code=hcodes.HTTP_BAD_FORBIDDEN)

        title = mem.customizer._configurations \
            .get('project', {}) \
            .get('title', "Unkown title")

        # invalidate previous reset tokens
        tokens = self.auth.get_tokens(user=user)
        for t in tokens:
            token_type = t.get("token_type")
            if token_type is None:
                continue
            if token_type != self.auth.PWD_RESET:
                continue

            tok = t.get("token")
            if self.auth.invalidate_token(tok):
                log.info("Previous reset token invalidated: %s", tok)

        # Generate a new reset token
        reset_token, jti = self.auth.create_temporary_token(
            user,
            duration=86400,
            token_type=self.auth.PWD_RESET
        )

        domain = os.environ.get("DOMAIN")
        if PRODUCTION:
            protocol = "https"
        else:
            protocol = "http"

        u = "%s://%s/public/reset/%s" % (protocol, domain, reset_token)
        body = "link to reset password: %s" % u

        replaces = {
            "url": u
        }
        html_body = get_html_template("reset_password.html", replaces)
        # html_body = "link to reset password: <a href='%s'>click here</a>" % u
        subject = "%s Password Reset" % title
        send_mail(html_body, subject, reset_email, plain_body=body)

        self.auth.save_token(
            user, reset_token, jti, token_type=self.auth.PWD_RESET)

        msg = "We are sending an email to your email address where " + \
            "you will find the link to enter a new password"
        return msg

    @decorate.catch_error()
    def put(self, token_id):

        try:
            # Unpack and verify token. If ok, self.auth will be added with
            # auth._user auth._token and auth._jti
            self.auth.verify_token(
                token_id, raiseErrors=True, token_type=self.auth.PWD_RESET)

        # If token is expired
        except jwt.exceptions.ExpiredSignatureError as e:
            raise RestApiException(
                'Invalid reset token: this request is expired',
                status_code=hcodes.HTTP_BAD_REQUEST)

        # if token is not yet active
        except jwt.exceptions.ImmatureSignatureError as e:
            raise RestApiException(
                'Invalid reset token',
                status_code=hcodes.HTTP_BAD_REQUEST)

        # if token does not exist (or other generic errors)
        except Exception as e:
            raise RestApiException(
                'Invalid reset token',
                status_code=hcodes.HTTP_BAD_REQUEST)

        # Recovering token object from jti
        token = self.auth.get_tokens(token_jti=self.auth._jti)
        if len(token) == 0:
            raise RestApiException(
                'Invalid reset token: this request is no longer valid',
                status_code=hcodes.HTTP_BAD_REQUEST)

        token = token.pop(0)
        emitted = timestamp_from_string(token["emitted"])

        # If user logged in after the token emission invalidate the token
        if self.auth._user.last_login is not None and \
                self.auth._user.last_login >= emitted:
            self.auth.invalidate_token(token_id)
            raise RestApiException(
                'Invalid reset token: this request is no longer valid',
                status_code=hcodes.HTTP_BAD_REQUEST)

        # If user changed the pwd after the token emission invalidate the token
        if self.auth._user.last_password_change is not None and \
                self.auth._user.last_password_change >= emitted:
            self.auth.invalidate_token(token_id)
            raise RestApiException(
                'Invalid reset token: this request is no longer valid',
                status_code=hcodes.HTTP_BAD_REQUEST)

        # The reset token is valid, do something

        data = self.get_input()
        new_password = data.get("new_password")
        password_confirm = data.get("password_confirm")

        # No password to be changed, just a token verification
        if new_password is None and password_confirm is None:
            return self.empty_response()

        # Something is missing
        if new_password is None or password_confirm is None:
            raise RestApiException(
                'Invalid password',
                status_code=hcodes.HTTP_BAD_REQUEST)

        if new_password != password_confirm:
            raise RestApiException(
                'New password does not match with confirmation',
                status_code=hcodes.HTTP_BAD_REQUEST)

        security = HandleSecurity(self.auth)

        security.change_password(
            self.auth._user, None, new_password, password_confirm)
        # I really don't know why this save is required... since it is already
        # in change_password ... But if I remove it the new pwd is not saved...
        self.auth._user.save()

        # Bye bye token (reset tokens are valid only once)
        self.auth.invalidate_token(token_id)

        return "Password changed"


class Tokens(EndpointResource):
    """ List all active tokens for a user """

    def get_user(self):

        iamadmin = self.auth.verify_admin()

        if iamadmin:
            username = self.get_input(single_parameter='username')
            if username is not None:
                username = username.lower()
                return self.auth.get_user_object(username=username)

        return self.get_current_user()

    def get(self, token_id=None):

        user = self.get_user()
        if user is None:
            return self.send_errors(
                message="Invalid: bad username", code=hcodes.HTTP_BAD_REQUEST)

        tokens = self.auth.get_tokens(user=user)
        if token_id is None:
            return tokens

        for token in tokens:
            if token["id"] == token_id:
                return token

        errorMessage = """Either this token was not emitted for your account
                          or it does not exist"""

        return self.send_errors(
            message=errorMessage, code=hcodes.HTTP_BAD_NOTFOUND)

    def delete(self, token_id=None):
        """
            For additional security, tokens are invalidated both
            by chanding the user UUID and by removing single tokens
        """

        user = self.get_user()
        if user is None:
            return self.send_errors(
                message="Invalid: bad username", code=hcodes.HTTP_BAD_REQUEST)

        if token_id is None:
            # NOTE: this is allowed only in removing tokens in unittests
            if not current_app.config['TESTING']:
                raise KeyError("TESTING IS FALSE! Specify a valid token")
            self.auth.invalidate_all_tokens(user=user)
            return self.empty_response()

        tokens = self.auth.get_tokens(user=user)

        for token in tokens:
            if token["id"] != token_id:
                continue
            if not self.auth.invalidate_token(token=token["token"], user=user):
                return self.send_errors(
                    message="Failed token invalidation: '%s'" % token,
                    code=hcodes.HTTP_BAD_REQUEST)
            log.debug("Token invalidated: %s", token_id)
            return self.empty_response()

        message = "Token not emitted for your account or does not exist"
        return self.send_errors(
            message=message, code=hcodes.HTTP_BAD_UNAUTHORIZED)


class Profile(EndpointResource):
    """ Current user informations """

    def get(self):

        current_user = self.get_current_user()
        data = {
            'uuid': current_user.uuid,
            'status': "Valid user",
            'email': current_user.email
        }

        # roles = []
        roles = {}
        for role in current_user.roles:
            # roles.append(role.name)
            roles[role.name] = role.name
        data["roles"] = roles
        data["isAdmin"] = self.auth.verify_admin()
        data["isGroupAdmin"] = self.auth.verify_group_admin()

        if hasattr(current_user, 'name'):
            data["name"] = current_user.name

        if hasattr(current_user, 'surname'):
            data["surname"] = current_user.surname

        if hasattr(current_user, 'irods_user'):
            data["irods_user"] = current_user.irods_user
            if not data["irods_user"]:
                data["irods_user"] = None
            elif data["irods_user"] == '':
                data["irods_user"] = None
            elif data["irods_user"] == '0':
                data["irods_user"] = None
            elif data["irods_user"][0] == '-':
                data["irods_user"] = None

        if self.auth.SECOND_FACTOR_AUTHENTICATION is not None:
            data['2fa'] = self.auth.SECOND_FACTOR_AUTHENTICATION

        return data

    @decorate.catch_error()
    def post(self):
        """ Create new current user """
        v = self.get_input()
        if len(v) == 0:
            raise RestApiException(
                'Empty input',
                status_code=hcodes.HTTP_BAD_REQUEST)
        # INIT #
        schema = self.get_endpoint_custom_definition()
        properties = self.read_properties(schema, v)
        # GRAPH #
        # properties["authmethod"] = "credentials"
        # if "password" in properties:
        # properties["password"] = \
        #     BaseAuthentication.hash_password(properties["password"])

        # DO CUSTOM STUFFS HERE - e.g. create irods user
        properties, other_properties = \
            self.custom_pre_handle_user_input(properties, v)

        roles = self.get_roles(v)
        user = self.auth.create_user(properties, roles)

        self.custom_post_handle_user_input(user, properties, other_properties)

        # DO CUSTOM STUFFS HERE - e.g. link to group
        return self.force_response(user.uuid)

    @decorate.catch_error()
    def put(self):
        """ Update profile for current user """

        user = self.auth.get_user()
        username = user.email
        # if user.uuid != uuid:
        #     msg = "Invalid uuid: not matching current user"
        #     raise RestApiException(msg)

        data = self.get_input()
        password = data.get('password')
        new_password = data.get('new_password')
        password_confirm = data.get('password_confirm')
        totp_authentication = (
            self.auth.SECOND_FACTOR_AUTHENTICATION is not None and
            self.auth.SECOND_FACTOR_AUTHENTICATION == self.auth.TOTP
        )
        if totp_authentication:
            totp_code = data.get('totp_code')
        else:
            totp_code = None

        security = HandleSecurity(self.auth)

        if new_password is None or password_confirm is None:
            msg = "New password is missing"
            raise RestApiException(msg, status_code=hcodes.HTTP_BAD_REQUEST)

        if totp_authentication:
            security.verify_totp(user, totp_code)
        else:
            # token, jti = self.auth.make_login(username, password)
            token, _ = self.auth.make_login(username, password)
            security.verify_token(username, token)

        security.change_password(
            user, password, new_password, password_confirm)
        # I really don't know why this save is required... since it is already
        # in change_password ... But if I remove it the new pwd is not saved...
        user.save()

        return self.empty_response()


###########################
# NOTE: roles are configured inside swagger definitions
class Internal(EndpointResource):
    """ Token and Role authentication test """

    def get(self):
        return "I am internal"


class Admin(EndpointResource):
    """ Token and Role authentication test """

    def get(self):
        return "I am admin!"


###########################
# In case you have celery queue,
# you get a queue endpoint for free
if detector.check_availability('celery'):

    class Queue(EndpointResource):

        def get(self, task_id=None):

            # Inspect all worker nodes
            celery = self.get_service_instance('celery')
            workers = celery.control.inspect()

            data = []

            active_tasks = workers.active()
            revoked_tasks = workers.revoked()
            scheduled_tasks = workers.scheduled()

            if active_tasks is None:
                active_tasks = []
            if revoked_tasks is None:
                revoked_tasks = []
            if scheduled_tasks is None:
                scheduled_tasks = []

            for worker in active_tasks:
                tasks = active_tasks[worker]
                for task in tasks:
                    if task_id is not None and task["id"] != task_id:
                        continue

                    row = {}
                    row['status'] = 'ACTIVE'
                    row['worker'] = worker
                    row['ETA'] = task["time_start"]
                    row['task_id'] = task["id"]
                    row['task'] = task["name"]
                    row['args'] = task["args"]

                    if task_id is not None:
                        task_result = celery.AsyncResult(task_id)
                        row['task_status'] = task_result.status
                        row['info'] = task_result.info
                    data.append(row)

            for worker in revoked_tasks:
                tasks = revoked_tasks[worker]
                for task in tasks:
                    if task_id is not None and task != task_id:
                        continue
                    row = {}
                    row['status'] = 'REVOKED'
                    row['task_id'] = task
                    data.append(row)

            for worker in scheduled_tasks:
                tasks = scheduled_tasks[worker]
                for task in tasks:
                    if task_id is not None and \
                       task["request"]["id"] != task_id:
                        continue

                    row = {}
                    row['status'] = 'SCHEDULED'
                    row['worker'] = worker
                    row['ETA'] = task["eta"]
                    row['task_id'] = task["request"]["id"]
                    row['priority'] = task["priority"]
                    row['task'] = task["request"]["name"]
                    row['args'] = task["request"]["args"]
                    data.append(row)

            # from celery.task.control import inspect
            # tasks = inspect()

            return self.force_response(data)

        def put(self, task_id):
            celery = self.get_service_instance('celery')
            celery.control.revoke(task_id)
            return self.empty_response()

        def delete(self, task_id):
            celery = self.get_service_instance('celery')
            celery.control.revoke(task_id, terminate=True)
            return self.empty_response()
