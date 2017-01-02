import boto3
import json
import datetime

sns = boto3.client('sns')

def lambda_handler(event, context):
    event["batch_end"] = str(datetime.datetime.utcnow())
    response = sns.list_topics()
    for topic in response["Topics"]:
        if topic["TopicArn"].endswith("eunomia_output"):
            response = sns.publish(
                TargetArn=topic["TopicArn"],
                Message=json.dumps(event)
            )
    return event
