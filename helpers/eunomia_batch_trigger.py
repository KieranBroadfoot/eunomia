from eunomia_core import *
import boto3
import json

# this function is utilised to monitor for SNS messages from Eunomia to determine if downstream
# batches should be executed.

read_s3 = boto3.resource('s3')

def lambda_handler(event, context):
    executing_arns = []
    for record in event["Records"]:
        input = json.loads(record["Sns"]["Message"])
        triggers = helper_get_s3_object_as_json(account_id=input["account_id"], path="triggers.json")
        for batch in triggers:
            if batch == input["batch_name"]:
                # found a matching trigger, iterate and execute
                for executing_batch in triggers[batch]:
                    batch = EunomiaBatch(account_id=input["account_id"],
                                         batch_name=executing_batch["batch_name"],
                                         batch_path=executing_batch["batch_path"],
                                         arn=executing_batch["batch"])
                    executing_arns.append(batch.execute_batch())
    return executing_arns