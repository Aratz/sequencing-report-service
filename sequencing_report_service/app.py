# -*- coding: utf-8 -*-
"""
Sets up routes and db for application, and allows it to be started.
"""

import logging
import functools

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from tornado.web import URLSpec as url
from tornado.ioloop import PeriodicCallback

from arteria.web.app import AppService

from alembic.config import Config as AlembicConfig
from alembic.command import upgrade as upgrade_db

from sequencing_report_service.handlers.version_handler import VersionHandler
from sequencing_report_service.handlers.job_handler import OneJobHandler, ManyJobHandler,\
    JobStartHandler, JobStopHandler
from sequencing_report_service.handlers.reports_handler import ReportFileHandler, ReportsHandler
from sequencing_report_service.services.local_runner_service import LocalRunnerService
from sequencing_report_service.repositiories.job_repo import JobRepository
from sequencing_report_service.repositiories.reports_repo import ReportsRepository
from sequencing_report_service.repositiories.runfolder_repo import RunfolderRepository
from sequencing_report_service.exceptions import ConfigurationError

log = logging.getLogger(__name__)


def routes(**kwargs):
    """
    Setup routes and feed them any kwargs passed, e.g.`routes(config=app_svc.config_svc)`
    Help will be automatically available at /api, and will be based on the
    doc strings of the get/post/put/delete methods
    :param: **kwargs will be passed when initializing the routes.
    """
    return [
        url(r"/api/1.0/version", VersionHandler, name="version", kwargs=kwargs),
        url(r"/api/1.0/jobs/start/(\w+)/(?!.*\/)(.*)$", JobStartHandler, name="job_start", kwargs=kwargs),
        url(r"/api/1.0/jobs/stop/(\d+)$", JobStopHandler, name="job_stop", kwargs=kwargs),
        url(r"/api/1.0/jobs/(\d+)$", OneJobHandler, name="one_job", kwargs=kwargs),
        url(r"/api/1.0/jobs/$", ManyJobHandler, name="many_jobs", kwargs=kwargs),
        url(r"/reports/(?!.*\/)(.*)$", ReportsHandler, name="all_reports", kwargs=kwargs),
        # Path is a required argument for the ReportsHandler (because it is subclassing the
        # static content handler, but it is not used. We use the configured repositories
        # to find the correct path for the report to serve. /JD 2018-11-27
        url(r"/reports/(.*)/$", ReportFileHandler, name="report", kwargs={**{'path': 'thisisnotused'}, **kwargs})
    ]


def create_and_migrate_db(db_engine, db_connection_string, logger_config_path, alembic_script_location):
    """
    Configures alembic and runs any none applied migrations found in the
    `scripts_location` folder.
    :param db_engine: engine handle for the database to apply the migrations to
    :param db_connection_string: connection string for db to migrate
    :param logger_config_path path to log config file for alembic
    :param alembic_script_location: path alemtic scripts
    :return: None
    """
    alembic_cfg = AlembicConfig()
    alembic_cfg.set_section_option("alembic", "log_config_file", logger_config_path)
    alembic_cfg.set_section_option("alembic", "sqlalchemy.url", db_connection_string)
    alembic_cfg.set_section_option("alembic", "script_location", alembic_script_location)

    with db_engine.begin() as connection:
        conn_attr = {"connection": connection}
        alembic_cfg.attributes = {**alembic_cfg.attributes, **conn_attr}
        upgrade_db(alembic_cfg, "head")


def get_key_from_config(config, key):
    """
    Get the specific key from the provided config object. Raises a ConfigurationError if the specified key
    does not exist in the configuration.
    :param config: dict-like object containing the config
    :param key: key to look up
    :return: the configuration value
    """
    try:
        return config[key]
    except KeyError as exc:
        raise ConfigurationError("{} not specified in config".format(key)) from exc


def configure_routes(config):
    """
    Configure and return the list of routes for the application
    :param config: a dict-like object containing the app config
    :return: a list of routes for the application
    """

    connection_string = get_key_from_config(config, 'db_connection_string')

    engine = create_engine(connection_string, echo=False)

    # Instantiate db, services, and repos
    log.info("Creating DB migrations")
    alembic_log_config_path = get_key_from_config(config, 'alembic_log_config_path')
    alembic_scripts_path = get_key_from_config(config, 'alembic_scripts')
    create_and_migrate_db(db_engine=engine,
                          db_connection_string=connection_string,
                          logger_config_path=alembic_log_config_path,
                          alembic_script_location=alembic_scripts_path)

    log.info("Setup connection to db")
    session_factory = scoped_session(sessionmaker())
    session_factory.configure(bind=engine)

    job_repo_factory = functools.partial(JobRepository, session_factory=session_factory)
    local_runner_service = LocalRunnerService(
        job_repo_factory,
        config['pipeline_config_dir'],
        config['nextflow_log_dirs'],
    )

    monitored_dirs = get_key_from_config(config, 'monitored_directories')
    runfolder_repo = RunfolderRepository(monitored_dirs)
    reports_dir = get_key_from_config(config, 'reports_dir')
    reports_repo = ReportsRepository(reports_dir=reports_dir)

    with job_repo_factory() as job_repo:
        job_repo.clear_out_stale_jobs_at_startup()

    return routes(config=config,
                  runner_service=local_runner_service,
                  runfolder_repo=runfolder_repo,
                  reports_repo=reports_repo)


def start(package=__package__):
    """
    Start the app
    """
    app_svc = AppService.create(package)
    config = app_svc.config_svc
    app_svc.start(configure_routes(config))
