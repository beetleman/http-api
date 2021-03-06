# -*- coding: utf-8 -*-

from setuptools import setup, find_packages
from restapi import \
    __package__ as main_package, \
    __version__ as current_version


swagger_dir = 'swagger'
app = '%s.__commands__' % main_package

setup(
    name='rapydo_http',
    version=current_version,
    description='HTTP API server working on top of the RAPyDo framework',
    url='https://rapydo.github.io/http-api',
    license='MIT',
    keywords=['http', 'api', 'rest', 'web', 'backend', 'rapydo'],
    author="Paolo D'Onorio De Meo",
    author_email='p.donorio.de.meo@gmail.com',
    packages=find_packages(
        where='.',
        exclude=['tests*']
    ),
    package_data={
        main_package: [
            'confs/services.yaml',
            '%s/*.yaml' % swagger_dir,
            '%s/*/*.yaml' % swagger_dir,
            'templates/index.html',
        ],
    },
    entry_points='''
        [console_scripts]
        %s=%s:cli
    ''' % (main_package, app),
    install_requires=[
        # Rapydo framework
        "rapydo-utils==%s" % current_version,
        # various utilities
        "attrs",
        "pyOpenSSL",
        "PyJWT",
        # Flask and plugins
        "Flask==0.12.2",
        "Flask-Cors",
        "Flask-OAuthlib",
        "Flask-RESTful",
        "Flask-SQLAlchemy",
        # "flask-shell-ipython",
        "flask_injector==0.10.1",
        "injector==0.12.0",
        # DB drivers
        "neomodel==3.2.6",
        # http://initd.org/psycopg/docs/install.html#binary-install-from-pypi
        # "psycopg2",
        "psycopg2-binary",
        "pymodm",
        # FS
        "python-irodsclient",
        "gssapi==1.4.1",
        # Swagger
        "bravado-core",
        "swagger-spec-validator",
    ],
    classifiers=[
        'Programming Language :: Python',
        'Intended Audience :: Developers',
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ]
)
