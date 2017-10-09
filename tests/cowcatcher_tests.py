#!/usr/bin/env python
"""
   Tests for cowcatcher.py
   Called via nosetests tests/cowcatcher_tests.py
"""

# Global imports
import unittest

from time import strftime
import boto3
import parsedatetime as pdt

# Local imports
import cowcatcher


class TestCowcatcher(unittest.TestCase):
    """
    Standard test class, for all cowcatcher functions
    """
    Bucket = 'cows-company-test-bucket'
    cons = pdt.Constants()
    cons.YearParseStyle = 0
    Pdtcal = pdt.Calendar(cons)
    Now_tm = Pdtcal.parse("now")
    Now_str = strftime('%c', Now_tm[0])
    @staticmethod
    def cowinfo_helper():
        """
        provide minimal cowdef for test
        """
        return {
            # Change Filters to {'Name':'tag:Name', 'Values':['*']} to restrict to named instances.
            'InstanceFilters' : 'Filters=[]',
            'DiscoverInstance' : 'describe_instances',
            'Service' : 'ec2',
            'S3Suffix' : 'TeamFoo',
            'InstanceIterator1' : 'Reservations',
            'InstanceIterator2' : 'Instances',
            'InstanceId' : 'InstanceId',
            'TagsKey' : 'Tags',
            'InstType' : 'InstanceType',
            'InstStateParent' : 'State',
            'InstStateChild' : 'Name',
            'DiscoverTags': None,
            'DiscoverTagsInstParm' : None,
            'CowReportARN' : 'arn:aws:sns:REPLACE_REGION:REPLACE_ACCOUNT:CowReport',
            'CurrentMetric' : 'CPUUtilization',
            'CowKeyChecklist' : ['REPLACE_KEY1', 'REPLACE_KEY2'],
            'CowActions' : [{'action': 'terminate', 'time_delta' : '-3 weeks',
                             'api_pre': 'terminate_instances(InstanceIds=["',
                             'api_post': '"])'},
                            {'action': 'stop', 'time_delta' : '-2 weeks',
                             'api_pre': 'stop_instances(InstanceIds=["',
                             'api_post': '"])'},
                            {'action': 'report', 'time_delta' : '-1 day',
                             'api_pre': None, 'api_post': None}]
        }

    def setUp(self):
        """
        set up if needed
        """
        print ""


    def tearDown(self):
        """
        tear down!
        """
        print ""


    def test_load_definition_file(self):
        """
        Test the method used for loading the team and service json
        """
        team_info = cowcatcher.load_definition_file(cowcatcher.TEAM_FILEPATH)
        self.assertEqual(len(team_info), 7)
        self.assertGreaterEqual(len(team_info['CowDefs']), 1)
        cowpath = cowcatcher.DEFS_PATH + team_info['CowDefs'][0]
        svc_info = cowcatcher.load_definition_file(cowpath)
        self.assertEqual(len(svc_info), 19)

    def test_load_bad_definition_file(self):
        """
        Test the loading method with malformed team json
        """
        bad_cowpath = cowcatcher.DEFS_PATH + 'team_bad.json'
        team_info = cowcatcher.load_definition_file(bad_cowpath)
        self.assertEqual(len(team_info), 0)

    def test_get_tag_keys(self):
        """
        Test the method that returns a list of keys
        """
        test_list = [{u'Key': 'Team', u'Value': 'TeamFoo'},
                     {u'Key': 'KubernetesCluster', u'Value': 'affirmative'},
                     {u'Key': 'k8s.io/role/master', u'Value': ''},
                     {u'Key': 'Name', u'Value': 'TeamFoo-REPLACE_REGION'},
                     {u'Key': 'Account', u'Value': 'REPLACE_ACCOUNT'},
                     {u'Key': 'autoscaling:groupName', u'Value': 'testgroupname'}]
        tag_keys = cowcatcher.get_tag_keys(test_list)
        self.assertEqual(len(tag_keys), 5)


    def test_get_service_instance_tags(self):
        """
        Test the method used for retrieving service instance tags
        """
        test_info = self.cowinfo_helper()
        test_client = boto3.client(test_info['Service'])
        insts = cowcatcher.get_service_instance_tags(test_client, test_info)
        self.assertGreaterEqual(len(insts), 2)
        for inst in insts:
            self.assertIn('tagkeys', inst)

    def test_analyze_write_roundup(self):
        """
        Test the method used for creating stats
        """
        test_info = self.cowinfo_helper()
        test_client = boto3.client(test_info['Service'])
        tags = cowcatcher.get_service_instance_tags(test_client, test_info)
        new_cows = cowcatcher.analyze_service_instances(tags, test_info)
        self.assertGreaterEqual(len(new_cows), 1)
        new_roundup = cowcatcher.handle_cows(new_cows, None, test_client, test_info,
                                             self.Pdtcal, self.Now_tm, self.Now_str)
        self.assertGreaterEqual(len(new_roundup), 2)
        cowfile = test_info['Service'] + '_' + test_info['S3Suffix'] + '.json'
        status = cowcatcher.save_roundup(new_roundup, self.Bucket, cowfile)
        self.assertEqual(status, 200)
        old_roundup = cowcatcher.load_roundup(self.Bucket, 'ec2_TeamFoo_test.json')
        self.assertEqual(len(old_roundup['cows']), 4)
        new_roundup = cowcatcher.handle_cows(new_cows, old_roundup, test_client, test_info,
                                             self.Pdtcal, self.Now_tm, self.Now_str)
        status = cowcatcher.save_roundup(new_roundup, self.Bucket, cowfile)
        self.assertEqual(status, 200)

    def test_load_roundup(self):
        """
        Test the method used for reading cowstats in s3
        """
        roundup = cowcatcher.load_roundup(self.Bucket, 'ec2_TeamFoo_test.json')
        self.assertEqual(len(roundup['cows']), 4)

    def test_format_send_report(self):
        """
        Test the method used for reading cowstats in s3
        """
        test_info = self.cowinfo_helper()
        roundup = cowcatcher.load_roundup(self.Bucket, 'ec2_TeamFoo_test.json')
        report_text = cowcatcher.format_report(roundup, test_info)
        self.assertEqual(len(report_text), 843)
        resp = cowcatcher.send_report(report_text, test_info, self.Now_str)
        self.assertEqual(resp.keys(), ['ResponseMetadata', 'MessageId'])

