(from https://github.com/rvrangel/cloudwatch-hipchat)
# sns-hipchat
AWS Lambda function to get a notification from SNS and post it to a Hipchat room

## Instructions

On Hipchat, create a new integration and get the auth token and room number, then add them the `hipchatToken` and `hipchatRoom` variables at the top of the `sns_hipchat.js` script.

On AWS you need to create a SNS topic that will receive your SNS notifications. After this, create this Lambda function and add the SNS topic as an Event Source. The Lambda Function will get the notifications from SNS and post it to your Hipchat room as soon as received.
