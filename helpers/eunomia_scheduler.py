import boto3
import botocore
import json
import time
import datetime

sfn = boto3.client('stepfunctions')
read_s3 = boto3.resource('s3')

def lambda_handler(event, context):
    try:
        obj = read_s3.Object("eunomia-"+event["account_id"], event["batch_path"]+"/input_set.json")
        input_set = json.loads(obj.get()['Body'].read().decode('utf-8'))
        input_set["account_id"] = event["account_id"]
        input_set["batch_begin"] = str(datetime.datetime.utcnow())
    except botocore.exceptions.ClientError:
        raise Exception("No input set for batch")
    exec_sfn = sfn.start_execution(
        stateMachineArn=event["batch"],
        name="eunomia_"+event["batch_name"]+"_"+str(time.time()),
        input=json.dumps(input_set)
    )
    return { "execution_arn": exec_sfn["executionArn"] }
