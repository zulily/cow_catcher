#!/usr/bin/env python
"""
cowcatcher worker
   Called by AWS Lambda to discover service instances
   which are then reported on and stopped/deleted.

   Copyright 2018 zulily, Inc.

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""


import json
import logging
from collections import defaultdict
from time import strftime

import boto3
from botocore.exceptions import ClientError, UnknownServiceError
import parsedatetime as pdt

Logger = logging.getLogger()
Logger.setLevel(logging.INFO)

S3_C = boto3.client('s3')
SNS_C = boto3.client('sns')
CLDTRL_C = boto3.client('cloudtrail')

# services cowcatcher has permission to search/delete
SERVICE_LIST = ['ec2', 'rds', 'autoscaling']

DEFS_PATH = 'cowdefs/'
TEAM_FILEPATH = DEFS_PATH + 'team.json'
MAX_SNS_MESSAGE = 1024 * 256

def load_definition_file(file_name):
    """
    Load JSON definition
    """
    try:
        with open(file_name, 'r') as deffile:
            mydict = json.load(deffile)
    except ValueError as error:
        mydict = ""
        Logger.warning('Failed to load file: %s', file_name)
        Logger.critical('Critical Error: %s', str(error))
    return mydict


def load_roundup(bucket, filename):
    """
    Load JSON cows from S3 file
    """
    try:
        obj = S3_C.get_object(Bucket=bucket, Key=filename)
        last_str = obj['Body'].read().decode('utf-8')
        cows = json.loads(last_str)
    except ClientError as err:
        if err.response['Error']['Code'] == "NoSuchKey":
            Logger.warning('No file found: %s', filename)
            cows = []
        else:
            raise

    return cows


def save_roundup(roundup, bucket, filename):
    """
    Save roundup to S3 json
    """
    try:
        out = S3_C.put_object(Bucket=bucket, Key=filename,
                              Body=json.dumps(roundup, ensure_ascii=False))
    except ClientError as err:
        Logger.error('Issue writing file:' + filename + ':' + err)

    return out['ResponseMetadata']['HTTPStatusCode']


def send_report(report_text, svc_info, now_str):
    """
    Publish report to AWS SNS endpoint
    Note: publish takes a max of 256KB.
    """
    overage = len(report_text) - MAX_SNS_MESSAGE
    if overage > 0:
        report_text = report_text[:-overage - 20] + '\n<message truncated/>'
    resp = SNS_C.publish(TopicArn=svc_info['CowReportARN'],
                         Message=report_text,
                         Subject='CowCatcher Report for ' + now_str)
    return resp


def handle_cows(new_cows, old_roundup, svc_client, svc_info, pdtcal, now_tm, now_str):
    """
    Handle (report/stop/terminate) all the new_cows, given rules and
    historical roundup info.
    """
    summary = defaultdict(int)
    roundup = {}

    if old_roundup:
        ocows = {a['id']:a for a in old_roundup['cows']}
    else:
        ocows = {}

    for ninst in new_cows:
        s_time = now_tm
        if ninst['id'] in ocows:
            ninst['initial_discovery'] = ocows[ninst['id']]['initial_discovery']
            s_time = pdtcal.parse(ocows[ninst['id']]['initial_discovery'])
            ninst['action_history'] = ocows[ninst['id']]['action_history']
        else:
            ninst['initial_discovery'] = now_str
            ninst['action_history'] = []
        for act in svc_info['CowActions']:
            if s_time > pdtcal.parse(act['time_delta']):
                #Action triggered
                summary[act['action']] += 1
                act_comment = act['action']  + ' at ' + now_str
                if act['api_pre']:
                    cmd = 'svc_client.' + act['api_pre'] + ninst['id'] + act['api_post']
                    eval(cmd)
                ninst['action_history'].append(act_comment)
                break

    roundup['action_summary'] = summary
    roundup['cows'] = new_cows
    roundup['last_run'] = now_str
    return roundup


def analyze_service_instances(svc_inst, svc_info):
    """
    Parse instances, finding wayward cows
    """
    badcows = []
    badinstid = []
    for inst in svc_inst:
        for keyreq in svc_info['CowKeyChecklist']:
            if keyreq not in inst['tags'] and \
               inst['id'] not in badinstid:
                inst['username'] = get_cloudtrail_username(inst['id'])
                badcows.append(inst)
                badinstid.append(inst['id'])

    return badcows


def format_report(cow_list, svc_info):
    """
    Given a service's roundup, return a string representation for email
    """
    output = 'Service: ' + svc_info['Service']
    output += '\n  CowCatcher run: ' + cow_list['last_run']
    if cow_list['cows']:
        output += '\n  Actions: '
        if cow_list['action_summary']:
            for change in cow_list['action_summary']:
                output += '\n    ' + change + ':   ' + str(cow_list['action_summary'][change])
        else:
            output += 'None'
        output += '\n  Untagged instances: '
        for cow in cow_list['cows']:
            output += '\n    ID:      ' + cow['id']
            if 'username' in cow and cow['username']:
                output += '\n      User:   ' + cow['username']
            if cow['state']:
                output += '\n      State:   ' + cow['state']
            if svc_info['InstType']:
                if cow['type']:
                    output += '\n      Type:    ' + cow['type']
            output += '\n      Found:   ' + cow['initial_discovery']
            if cow['tags']:
                output += '\n      Tags:'
                for tag in cow['tags']:
                    output += '\n           '
                    output += tag + ' : ' + cow['tags'][tag]
            if cow['action_history']:
                output += '\n      History: '
                for action in cow['action_history']:
                    output += '\n        ' + action
    else:
        output += '\n  No untagged instances.'
    output += '\n\n'

    return output


def get_tag_keys(key_list):
    """
    Return a dict of tags with non-null values
    """
    return {i['Key']:i['Value'] for i in key_list if i['Value']}


def discover_instance_tags(instances, svc_client, svc_info):
    """
    Retrieve tags from the given instances
    """
    discoveries = []
    for inst in instances:
        stats = {}
        stats['id'] = inst[svc_info['InstanceId']]
        if svc_info['InstType']:
            stats['type'] = inst[svc_info['InstType']]
        # If state is in dict of dict
        if svc_info['InstStateChild']:
            tmp = inst[svc_info['InstStateParent']]
            if isinstance(tmp, list):
                # handle autoscale, etc. by choosing first instance
                try:
                    tmp = tmp[0]
                except IndexError:
                    tmp = {}
                    tmp[svc_info['InstStateChild']] = 'NoInstances'

            stats['state'] = tmp[svc_info['InstStateChild']]
        else:
            stats['state'] = inst[svc_info['InstStateParent']]
        # Requires another API call
        if svc_info['DiscoverTags']:
            cmd = 'svc_client.' + svc_info['DiscoverTags']
            if svc_info['DiscoverTagsInstParm']:
                cmd += 'inst["' + svc_info['DiscoverTagsInstParm'] + '"]'
            cmd += ')'
            response = eval(cmd)
            try:
                stats['tags'] = get_tag_keys(response[svc_info['TagsKey']])
            except KeyError:
                stats['tags'] = {}
        else:
            try:
                stats['tags'] = get_tag_keys(inst[svc_info['TagsKey']])
            except KeyError:
                stats['tags'] = {}

        discoveries.append(stats)

    return discoveries

def parse_service_response(response, inst_iter1, inst_iter2):
    """
    Handle paginated response from service
    """
    inst = []
    if inst_iter2:
        # Two levels of lists
        for tmp in response[inst_iter1]:
            for tmp2 in tmp[inst_iter2]:
                inst.append(tmp2)
    elif inst_iter1:
        for tmp in response[inst_iter1]:
            inst.append(tmp)
    else:
        inst = response

    return inst


def get_service_instance_tags(svc_client, svc_info):
    """
    Retrieve instances for the given service,
    Flattening AWS structure if necessary
    """
    instances = []

    paginator = svc_client.get_paginator(svc_info['DiscoverInstance'])
    if svc_info['InstanceFilters']:
        for response in paginator.paginate(Filters=svc_info['InstanceFilters']):
            instances.extend(parse_service_response(response, svc_info['InstanceIterator1'],
                                                    svc_info['InstanceIterator2']))
    else:
        for response in paginator.paginate():
            instances.extend(parse_service_response(response, svc_info['InstanceIterator1'],
                                                    svc_info['InstanceIterator2']))

    return discover_instance_tags(instances, svc_client, svc_info)


def get_cloudtrail_username(rsc_name):
    """
    Given resource name, search cloudtrail for oldest record, return username
    associated with record.
    """
    username = ''
    events = []

    lookup = [{'AttributeKey':'ResourceName',
               'AttributeValue': rsc_name}]
    paginator = CLDTRL_C.get_paginator('lookup_events')
    # walk through all records. This should only happen for new instances.
    for response in paginator.paginate(LookupAttributes=lookup):
        events.extend(response['Events'])
    for event in events[::-1]:
        # Find a non-empty username
        if 'Username' in event and event['Username']:
            username = event['Username']
            break

    return username


def main(event, context):
    """
    Main functionality
    """
    all_issues = ''

    cons = pdt.Constants()
    cons.YearParseStyle = 0
    pdtcal = pdt.Calendar(cons)
    now_tm = pdtcal.parse("now")
    now_str = strftime('%c', now_tm[0])

    team_info = load_definition_file(TEAM_FILEPATH)

    for svc in team_info['CowDefs']:

        svc_info = load_definition_file(DEFS_PATH + svc)

        #   Ensure API exists for service
        try:
            svc_client = boto3.client(svc_info['Service'])
        except UnknownServiceError:
            Logger.critical('Service unknown to AWS API: %s', svc_info['Service'])

        if svc_info['Service'] in SERVICE_LIST:
            inst_tags = get_service_instance_tags(svc_client, svc_info)
            new_cows = analyze_service_instances(inst_tags, svc_info)
            cowfile = svc_info['Service'] + '_' + svc_info['S3Suffix'] + '.json'
            old_roundup = load_roundup(team_info['Bucket'], cowfile)
            new_roundup = handle_cows(new_cows, old_roundup, svc_client, svc_info,
                                      pdtcal, now_tm, now_str)
            http_status = save_roundup(new_roundup, team_info['Bucket'], cowfile)
            if http_status <> 200:
                Logger.error('Unable to write roundup file: %s', cowfile)

            report_text = format_report(new_roundup, svc_info)
            all_issues += report_text
            if svc_info['CreateServiceReport']:
                send_report(report_text, svc_info, now_str)
        else:
            Logger.warning('No permissions for retrieving instances. Service: ')
            Logger.warning(svc_info['Service'])

    if team_info['CreateTeamReport']:
        send_report(all_issues, svc_info, now_str)


#main('foo', 'bar')
