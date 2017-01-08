import boto3
import botocore
import json
import time
import datetime

sfn = boto3.client('stepfunctions')
read_s3 = boto3.resource('s3')

def lambda_handler(event, context):
    for record in event["Records"]:
        message = record["Sns"]["Message"]
        input = json.loads(message)
        trigger_file = read_s3.Object("eunomia-"+input["account_id"], "triggers.json")
        triggers = json.loads(trigger_file.get()['Body'].read().decode('utf-8'))
        executing_arns = []
        for batch in triggers:
            if batch == input["batch_name"]:
                # found a matching trigger, iterate and execute
                for executing_batch in triggers[batch]:
                    try:
                        obj = read_s3.Object("eunomia-"+input["account_id"], executing_batch["batch_path"]+"/input_set.json")
                        input_set = json.loads(obj.get()['Body'].read().decode('utf-8'))
                        input_set["batch_begin"] = str(datetime.datetime.utcnow())
                        input_set["account_id"] = event["account_id"]
                    except botocore.exceptions.ClientError:
                        raise Exception("No input set for batch")
                    exec_sfn = sfn.start_execution(
                        stateMachineArn=executing_batch["batch"],
                        name="eunomia_"+executing_batch["batch_name"]+"_"+str(time.time()),
                        input=json.dumps(input_set)
                    )
                    executing_arns.append(exec_sfn["executionArn"])
    return executing_arns