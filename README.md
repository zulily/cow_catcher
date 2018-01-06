# CowCatcher 
### Managing non-tagged service instances AWS

Keeping track of your instances in AWS is quite a task. This tool (CowCatcher), run routinely from AWS Lambda, will detect your instances, and if they don't conform to given tag criteria, can report, stop, and/or delete them based on your time criteria.
(Note: this approach is related to "cattle" approach in the AWS cloud [(link)](http://cloudscaling.com/blog/cloud-computing/the-history-of-pets-vs-cattle/), and can easily recover from a deleted VM.)

## Setup
There are a few things you need to do to set this up for yourself (see details below):  
 
  - Create the AWS Simple Notification Service (SNS) topics/subscriptions for notifying teams.
  - Customize the JSON templates in the `cowdefs` directory to match the services you want to manage.
  - Package and deploy the lambda function to AWS.

### Create AWS SNS topics/subscriptions
CowCatcher uses AWS SNS to handle notifications of issues found during cow catching. Various SNS topic/subscriptions can be created as follows:

 - Create a PagerDuty integration for SNS following the process here: [link](https://www.pagerduty.com/docs/guides/aws-cloudwatch-integration-guide/)  (ARN is available following Step 4. of the "AWS SNS Console" section.) 
 - Create a Slack integration for SNS by creating another AWS Lambda function, which pushes SNS events to the Slack Chat server. The description of the AWS Lambda template is found here: [link](https://aws.amazon.com/blogs/aws/new-slack-integration-blueprints-for-aws-lambda/).
 - Create a hipchat integration by creating another AWS Lambda function, as provided here: [link](https://github.com/zulily/cow_catcher/tree/master/sns_integrations)
 - Create an email integration, using the AWS process here: [link](http://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/US_SetupSNS.html).

### Customize the JSON templates

* Edit `team.json` to modify:

 - `Bucket` : Set to a bucket you create for keeping statistics on CowCatcher. If you keep the "cows" prefix, your lambda function can write to it.
 - `Team` : Set to your team's name.
 - `CreateTeamReport` : Set to false if you don't want a report with all non-tagged instances.
 - `CowDefs` list : Change to reference only the services' files on which you plan to alert.

* Copy each service you want to check (e.g., `ec2_TeamFoo.json`) to a new filename (referencing it in the `team.json` `CowDefs` list.)  In the new file, modify:

 - `InstanceFilters` : If your instances have names, add `tag:Name` key's values if you want to restrict tag analysis to a subset of instances.  (If you do this, you also should to change the `S3Suffix` to keep CowCatcher data files separate.) Example:
`   "InstanceFilters" : [ 
      {
          "Name": "tag:Name", 
          "Values":["foo*"]
      },
      {
          "Name":"instance-state-name",
          "Values":["running"]
      } 
  ]`
 - `CowKeyChecklist` : Modify to include the list of all mandatory instance tags for the given service, replacing/adding to `REPLACE_KEY1` and `REPLACE_KEY2`.
 - `CowActions` : This list defines the actions that are taken for all instances found which don't have the mandatory keys defined in `CowKeyChecklist`. 
	 - Remove any action (i.e., ` {"action": "terminate", .. "api_post": *"}`) that is inappropriate for your environment! For example, remove the `terminate` action in the `rds_*.json` if you don't want to terminate RDS instances. 
	 - Adjust `time_delta` to the appropriate time (since CowCatcher discovery) before triggering the given action. Ensure that the Actions list remains in order of decreasing `time_delta`.
 - `CreateServiceReport` : Set to false if you don't want a separate report on all non-conforming instances in the given service.
 - `CowReportARN` : Modify to include the SNS topic/subscription ARN you created in the previous section for the issues found/handled by CowCatcher.

The packaging step will deploy everything in the cowdefs directory to the Lambda zip file (so you may wish to remove templates/files you don't use).
	
	
### Package and deploy the lambda function

1. Edit `vars.sh` to set the rate for the lambda function to run inside your VPC.
1. Run `./deploy_lambda_function.sh`.  This will:

* Package up the script with its dependencies into the zip format that AWS Lambda expects (as defined in `package.sh`).
* Interact with the AWS API to set up the lambda function with the things it needs (as defined in `deployscripts/setup_lambda.py`):
  * Creates an IAM role for the lambda function to use.  Review the json files in the `deployscripts` directory to see the permissions required.
  * Uploads the zip file from the previous step to create a Lambda function (possibly publishing a new version if the function 
  already exists).
  
### Running the test suite (optional)

Note: the `tests/cowcatcher_tests.py` test suite requires configuration to successfully execute a unit test in your environment:

1. Create/use a test Account in AWS to use for validation. Ensure your current AWS credentials give you full access to that account.
2. Create a S3 test bucket in your test account, with credentials for read/write access by the current user. Copy the `ec2_TeamFoo_test.json` file from the `tests` subdirectory to that test bucket.
2. Modify the `cowcatcher_tests.py` file to set the `Bucket` class variable value to your S3 test bucket name.
3. Ensure there is an EC2 instance running in your test account, tagged with keys that are identified in the `CowKeyChecklist`.  If you automatically tag your instances (best practice), substitute your keys' key names for the `REPLACE_KEY1` and `REPLACE_KEY2` variables in the `cowinfo_helper()` method of the `cowcatcher_tests.py` file.
4. Create an SNS topic in your test Account (email), then use that `Topic ARN` as the value of the `CowReportARN` variable in the `cowcatcher_tests.py` file.

 
