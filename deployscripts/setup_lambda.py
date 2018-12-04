#!/usr/bin/env python
"""
setup_lambda script
   Used to deploy python app to AWS Lambda, creating roles needed and
   pushing the script to AWS Lambda.

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

import os
from time import sleep

import boto3
from botocore.exceptions import ClientError

IAM_R = boto3.resource('iam')
IAM_C = boto3.client('iam')
LAMBDA_C = boto3.client('lambda')
EVENTS_C = boto3.client('events')

BASE_DIR = os.path.dirname(os.path.realpath(__file__))
SVC_ACCESS = ['cloudwatch_access','ec2_access', 'sns_access', 'rds_access',
              'as_access', 's3_access', 'cloudtrail_access']

def setup_iam_role():
    """
    Setup the AWS IAM role
    """
    try:
        IAM_C.get_role(RoleName='aws_cowcatcher')
    except ClientError as err:
        if err.response['Error']['Code'] == 'NoSuchEntity':
            with open('{}/lambda_role_policy.json'.format(BASE_DIR), 'r') as policy_file:
                policy = policy_file.read()
                IAM_C.create_role(RoleName='aws_cowcatcher',
                                  AssumeRolePolicyDocument=policy)
        else:
            raise err

    for pol in SVC_ACCESS:
        with open('{}/{}.json'.format(BASE_DIR, pol), 'r') as policy_file:
            policy = policy_file.read()
            IAM_C.put_role_policy(RoleName='aws_cowcatcher',
                                  PolicyName=pol,
                                  PolicyDocument=policy)
    try:
        IAM_C.get_instance_profile(InstanceProfileName='aws_cowcatcher')
    except ClientError as err:
        if err.response['Error']['Code'] == 'NoSuchEntity':
            IAM_C.create_instance_profile(InstanceProfileName='aws_cowcatcher')
        else:
            raise err

    role_instance_profiles = IAM_C.list_instance_profiles_for_role(RoleName='aws_cowcatcher')
    add_instance_profile = True
    for profile in role_instance_profiles['InstanceProfiles']:
        if profile['InstanceProfileName'] == 'aws_cowcatcher':
            add_instance_profile = False
    if add_instance_profile:
        IAM_C.add_role_to_instance_profile(InstanceProfileName='aws_cowcatcher',
                                           RoleName='aws_cowcatcher')
    return IAM_R.Role('aws_cowcatcher')

def configure_vpc():
    """
    Provide vpc/sg for lambda function
    """
    vpc_config = {}
    subnet_id = os.environ.get('SUBNET_ID')
    security_group_id = os.environ.get('SECURITY_GROUP_ID')
    if subnet_id:
        vpc_config['SubnetIds'] = [subnet_id]
    if security_group_id:
        vpc_config['SecurityGroupIds'] = [security_group_id]
    return vpc_config

def upload_lambda_function():
    """
    main function of deployment.
    Ensure IAM is setup. Upload zip. Create function.
    """
    vpc_config = configure_vpc()
    role = setup_iam_role()

    rule = EVENTS_C.put_rule(Name='DiscoverCowsSchedule',
                             ScheduleExpression=os.environ.get('DISCOVERY_SCHEDULE'),
                             State='ENABLED',
                             Description='Run the instance discovery')

    with open('{}/../aws_cowcatcher.zip'.format(BASE_DIR), 'rb') as zip_file:
        zip_bytes = zip_file.read()
        fcn = {}
        try:
            LAMBDA_C.get_function(FunctionName='DiscoverCows')
            fcn = LAMBDA_C.update_function_code(FunctionName='DiscoverCows',
                                                ZipFile=zip_bytes,
                                                Publish=True)
        except ClientError as err:
            if err.response['Error']['Code'] == 'ResourceNotFoundException':
                sleep(10)
                fcn = LAMBDA_C.create_function(FunctionName='DiscoverCows',
                                               Code={'ZipFile': zip_bytes},
                                               Runtime='python2.7',
                                               Role=role.arn,
                                               Handler='cowcatcher.main',
                                               Timeout=300,
                                               Description="Report, stop, kill cows (instances)",
                                               MemorySize=128,
                                               VpcConfig=vpc_config)

            else:
                raise err

        try:
            LAMBDA_C.add_permission(FunctionName='DiscoverCows',
                                    StatementId='DiscoverCowsSchedule-Permission',
                                    Action='lambda:InvokeFunction',
                                    Principal='events.amazonaws.com',
                                    SourceArn=rule['RuleArn'])
        except ClientError as err:
            if err.response['Error']['Code'] != 'ResourceConflictException':
                # ignore conflicts if the rule exists
                raise err

        EVENTS_C.put_targets(Rule='DiscoverCowsSchedule',
                             Targets=[{'Id': 'DiscoverCows-schedule',
                                       'Arn': fcn['FunctionArn'],}])

upload_lambda_function()
