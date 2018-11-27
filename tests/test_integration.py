import json
import codecs

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from sequencing_report_service.app import compose_application

from sequencing_report_service import __version__ as version


class TestIntegration(AsyncHTTPTestCase):
    def get_app(self):
        config = {}
        return Application(compose_application(config))

    def test_get_version(self):
        response = self.fetch('/api/1.0/version')
        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), {'version': version})

    def test_start_job(self):
        response = self.fetch('/api/1.0/jobs/start/foo', method='POST', body=json.dumps({}))
        self.assertEqual(response.code, 202)
        status_link = json.loads(response.body).get('link', None)
        self.assertTrue(status_link)
        status_response = self.fetch(status_link)
        self.assertTrue(json.loads(status_response.body).get('job_id'))
        self.assertTrue(json.loads(status_response.body).get('status'))

    def test_stop_job(self):
        # First start the job
        response = self.fetch('/api/1.0/jobs/start/foo', method='POST', body=json.dumps({}))
        self.assertEqual(response.code, 202)
        status_link = json.loads(response.body).get('link', None)
        self.assertTrue(status_link)
        status_response = self.fetch(status_link)
        body_as_dict = json.loads(status_response.body)
        self.assertTrue(body_as_dict.get('job_id'))
        self.assertTrue(body_as_dict.get('status'))

        # Then stop it
        stop_response = self.fetch('/api/1.0/jobs/stop/{}'.format(body_as_dict['job_id']),
                                   method='POST',
                                   body=json.dumps({}))

        self.assertEqual(stop_response.code, 202)

        # And check its status
        status_after_stop_response = self.fetch(json.loads(stop_response.body)['link'])
        self.assertEqual(json.loads(status_after_stop_response.body)['status'], 'cancelled')

    def test_should_return_report(self):
        response = self.fetch('/reports/foo_runfolder/')
        self.assertEqual(response.code, 200)
        decoded_body = response.body.decode('UTF-8')
        self.assertIn('MultiQC', decoded_body)
        self.assertIn('VERSION2', decoded_body)

    def test_should_return_specific_report(self):
        response = self.fetch('/reports/foo_runfolder/v1')
        self.assertEqual(response.code, 200)
        decoded_body = response.body.decode('UTF-8')
        self.assertIn('MultiQC', decoded_body)
        self.assertIn('VERSION1', decoded_body)
