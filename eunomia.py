#!/usr/bin/env python
#
# Kieran J. Broadfoot - 2017
#

import sys
import os
import argparse
import yaml
import boto3
import botocore
import json
import time
import datetime
import glob
import tempfile
import shutil
import zipfile
import base64
import subprocess
import platform
from Crypto.Cipher import AES

def get_parser():
    parsers = {}
    parsers['super'] = argparse.ArgumentParser(description="A simple batch scheduler")
    parsers['super'].add_argument("-r", "--region", help="the AWS region to use")
    subparsers = parsers['super'].add_subparsers(help='Try commands like "{name} generate -h" or "{name} execute --help" to get each sub command\'s options'.format(name=sys.argv[0]))
    parsers['list'] = subparsers.add_parser('list', help='list available configurations')
    parsers['list'].add_argument("type", type=str, help="view: batch, secrets")
    parsers['list'].set_defaults(action='list')
    parsers['generate'] = subparsers.add_parser('generate', help='generate a batch definition')
    parsers['generate'].add_argument("file", type=str, help="yaml batch definition")
    parsers['generate'].set_defaults(action='generate')
    parsers['execute'] = subparsers.add_parser('execute', help='manually execute a batch definition')
    parsers['execute'].add_argument("name", type=str, help="the name of the batch definition")
    parsers['execute'].add_argument("version", type=str, help="the version of the batch definition")
    parsers['execute'].set_defaults(action='execute')
    parsers['delete'] = subparsers.add_parser('delete', help='delete a batch definition')
    parsers['delete'].add_argument("name", type=str, help="the name of the batch definition")
    parsers['delete'].add_argument("version", type=str, help="the version of the batch definition")
    parsers['delete'].set_defaults(action='delete')
    parsers['setup'] = subparsers.add_parser('setup', help='setup the Eunomia batch service')
    parsers['setup'].add_argument("type", type=str, help="type of setup: all, global, region, update_lambda")
    parsers['setup'].set_defaults(action='setup')
    parsers['secret'] = subparsers.add_parser('secret', help='configure secrets for Eunomia batch service')
    parsers['secret'].add_argument("type", type=str, help="actions: add, delete")
    parsers['secret'].add_argument("name", type=str, help="name of secret")
    parsers['secret'].add_argument("-f", "--filename", help="file containing the secret")
    parsers['secret'].add_argument("-t", "--text", help="text containing the secret")
    parsers['secret'].set_defaults(action='secret')
    return parsers

def main():
    config = {}
    parsers = get_parser()
    args = parsers['super'].parse_args()
    config["accountid"] = boto3.client('sts').get_caller_identity().get('Account')
    config["region"] = args.region
    if not config["region"]:
        session = boto3.session.Session()
        config["region"] = session.region_name
    print "Eunomia: { 'AccountID': '"+config["accountid"]+"', 'Region': '"+config["region"]+"' }"
    if "action" in vars(args):
        if args.action == "list":
            list_configuration(config, args)
            return
        if args.action == "generate":
            generate_state_machine(config, args)
            return
        if args.action == "execute":
            execute_state_machine(config, args)
            return
        if args.action == "delete":
            delete_state_machine(config, args)
            return
        if args.action == "setup":
            setup(config, args)
            return
        if args.action == "secret":
            secret(config, args)
            return
    else:
        parsers['super'].print_help()

def list_configuration(config, args):
    filter = "batch"
    if args.type == "secrets":
        filter = "secrets"
    configuration_items = []
    s3 = boto3.client('s3')
    try:
        for key in s3.list_objects(Bucket="eunomia-"+config["accountid"])['Contents']:
            if filter not in key['Key'] or "/." in key['Key']:
                continue
            path = key['Key'].split("/")
            if filter == "batch":
                name = path[1]+" ("+path[2]+")"
            else:
                name = path[1]
            if name not in configuration_items:
                configuration_items.append(name)
    except KeyError:
        print "Empty Bucket: No Configuration Available"
        sys.exit(1)

    print "Available:"
    count = 0
    for task in configuration_items:
        print str(count)+": "+task
        count += 1

def generate_state_machine(config, args):
    sfn = boto3.client('stepfunctions', region_name=config["region"])
    s3 = boto3.resource('s3')
    events = boto3.client('events', region_name=config["region"])
    lambda_client = boto3.client('lambda', region_name=config["region"])
    input_set = { 'input': {}, 'output': {}}
    state_machine = {}
    with open(args.file, 'r') as stream:
        try:
            data = yaml.load(stream)
            list_of_task_types = ["wait", "end", "custom"]
            list_of_task_types = list_of_task_types + map(lambda x: x.replace("eunomia_",""), generate_list_of_lambda_functions(config))
            list_of_task_types.remove("scheduler")
            list_of_task_types.remove("batch_trigger")
            if check_validity_of_data(data, list_of_task_types):
                state_machine["Comment"] = data["name"]+" (v"+str(data["version"])+") generated by Eunomia to execute at: "+data["execute"]
                state_machine["StartAt"] = data["start_at"]
                state_machine["States"] = {}
                for idx,task in enumerate(data["tasks"]):
                    input_set = update_input_data_set(input_set, task, data["tasks"][task])
                    state_machine = generate_sfn(config, state_machine, task, data["tasks"][task])
                short_name = data["name"].replace(" ","_")
                version = "v"+str(data["version"])
                sfn_name = "eunomia_"+short_name+"_"+version
                input_set["batch_name"] = sfn_name
                s3_path = "batch/"+short_name+"/"+version
                s3.Bucket("eunomia-"+config["accountid"]).put_object(Key=s3_path+"/state_machine.json",Body=json.dumps(state_machine))
                s3.Bucket("eunomia-"+config["accountid"]).put_object(Key=s3_path+"/input_set.json",Body=json.dumps(input_set))
                response = sfn.create_state_machine(
                    name = sfn_name,
                    definition = json.dumps(state_machine),
                    roleArn="arn:aws:iam::"+config["accountid"]+":role/eunomia_execution_role_"+config["region"]
                )
                sfn_arn = response["stateMachineArn"]
                print "Generated Batch at: "+sfn_arn
                schedule_input = {
                    "batch": sfn_arn,
                    "batch_name": short_name+"_"+version,
                    "batch_path": s3_path,
                    "account_id": config["accountid"]
                }
                if "batch" in data["execute"]:
                    execution = data["execute"].replace("batch(","")
                    execution = execution.replace(")","")
                    execution_batch = execution.split()
                    executing_batch_version = execution_batch[-1]
                    executing_batch_name = '_'.join(execution_batch[:-1])
                    executing_full_name = "eunomia_"+executing_batch_name+"_v"+executing_batch_version
                    triggers = {}
                    try:
                        obj = s3.Object("eunomia-"+config["accountid"], "triggers.json")
                        triggers = json.loads(obj.get()['Body'].read().decode('utf-8'))
                    except botocore.exceptions.ClientError:
                        pass
                    if executing_full_name not in triggers:
                        triggers[executing_full_name] = []
                    triggers[executing_full_name].append(schedule_input)
                    s3.Bucket("eunomia-"+config["accountid"]).put_object(Key="triggers.json",Body=json.dumps(triggers))
                    print "Created Trigger for: "+executing_full_name
                else:
                    response = lambda_client.list_functions(
                        MaxItems=100
                    )
                    scheduler_arn = ""
                    for func in response["Functions"]:
                        if "eunomia_scheduler" in func["FunctionName"]:
                            scheduler_arn = func["FunctionArn"]
                    if not scheduler_arn:
                        print "ERROR: Unable to find scheduler, cannot complete scheduling"
                        sys.exit(1)
                    rule_name = "eunomia_rule_"+short_name+"_"+version
                    response = events.put_rule(
                        Name=rule_name,
                        ScheduleExpression=data["execute"],
                        State='ENABLED',
                        Description="Eunomia Scheduler for "+short_name+" "+version,
                        RoleArn="arn:aws:iam::748992736554:role/eunomia_execution_role_eu-west-1"
                    )
                    rule_arn = response["RuleArn"]
                    response = events.put_targets(
                        Rule=rule_name,
                        Targets=[
                            {
                                'Id': '1',
                                'Arn': scheduler_arn,
                                'Input': json.dumps(schedule_input)
                            },
                        ]
                    )
                    print "Generated Schedule at: "+rule_arn
        except yaml.YAMLError as exc:
            print(exc)

def execute_state_machine(config, args):
    sfn = boto3.client('stepfunctions', region_name=config["region"])
    task_id = args.name+"_"+args.version
    path_id = "batch/"+args.name+"/"+args.version
    read_s3 = boto3.resource('s3')
    try:
        obj = read_s3.Object("eunomia-"+config["accountid"], path_id+"/input_set.json")
        input_set = json.loads(obj.get()['Body'].read().decode('utf-8'))
    except botocore.exceptions.ClientError:
        print "No such state machine"
        sys.exit(1)
    input_set["batch_begin"] = str(datetime.datetime.utcnow())
    input_set["account_id"] = config["accountid"]
    response = sfn.list_state_machines(
        maxResults=1000
    )
    sfn_arn = ""
    for key in response["stateMachines"]:
        if key["name"] == "eunomia_"+task_id:
            sfn_arn = key["stateMachineArn"]
    if not sfn_arn:
        print "No valid State Machine available."
        sys.exit(1)
    else:
        exec_sfn = sfn.start_execution(
            stateMachineArn=sfn_arn,
            name="eunomia_"+task_id+"_"+str(time.time()),
            input=json.dumps(input_set)
        )
        print "Executing: "+exec_sfn["executionArn"]

def delete_state_machine(config, args):
    s3 = boto3.client('s3')
    sfn = boto3.client('stepfunctions', region_name=config["region"])
    events = boto3.client('events', region_name=config["region"])
    task_id = args.name+"_"+args.version
    path_id = "batch/"+args.name+"/"+args.version
    s3.delete_object(Bucket="eunomia-"+config["accountid"], Key=path_id+"/input_set.json")
    print "Deleted Input Set."
    s3.delete_object(Bucket="eunomia-"+config["accountid"], Key=path_id+"/state_machine.json")
    print "Deleted JSON Definition."
    try:
        response = events.describe_rule(
            Name="eunomia_rule_"+task_id,
        )
        response = events.remove_targets(
            Rule="eunomia_rule_"+task_id,
            Ids=['1']
        )
        response = events.delete_rule(
            Name="eunomia_rule_"+task_id
        )
        print "Deleted Schedule"
    except botocore.exceptions.ClientError:
        # rule doesnt exist.... check for batch trigger
        try:
            obj = s3.get_object(Bucket="eunomia-"+config["accountid"], Key="triggers.json")
            triggers = json.loads(obj['Body'].read().decode('utf-8'))
            for key in triggers:
                for index, element in enumerate(triggers[key]):
                    if triggers[key][index]["batch_name"] == task_id:
                        del triggers[key][index]
            s3.put_object(Bucket="eunomia-"+config["accountid"], Key="triggers.json",Body=json.dumps(triggers))
            print "Deleted Trigger"
        except botocore.exceptions.ClientError:
            print "No Rule or Trigger found for Batch!"
            pass
    response = sfn.list_state_machines(
        maxResults=1000
    )
    sfn_arn = ""
    for key in response["stateMachines"]:
        if key["name"] == "eunomia_"+task_id:
            sfn_arn = key["stateMachineArn"]

    if not sfn_arn:
        print "No valid State Machine available."
        sys.exit(1)
    else:
        response = sfn.delete_state_machine(
            stateMachineArn=sfn_arn
        )
        print "Deleted State Machine."

def setup(config, args):
    if args.type == "all":
        setup_global(config)
        setup_region(config)
    elif args.type == "global":
        setup_global(config)
    elif args.type == "region":
        setup_region(config)
    elif args.type == "update_lambda":
        setup_lambda(config)

def setup_global(config):
    iam = boto3.client('iam')
    s3 = boto3.client('s3', region_name=config["region"])
    policy = { "Version": "2012-10-17",
        "Statement": [
            { "Action": [ "sns:Publish", "sns:ListTopics" ], "Effect": "Allow", "Resource": "arn:aws:sns:*:"+config["accountid"]+":*" },
            { "Action": [ "lambda:InvokeFunction","lambda:InvokeAsync" ], "Effect": "Allow", "Resource": "arn:aws:lambda:*:"+config["accountid"]+":function:eunomia_*" },
            { "Action": [ "states:StartExecution" ], "Effect": "Allow", "Resource": "arn:aws:states:*:"+config["accountid"]+":stateMachine:eunomia_*" },
            { "Action": [ "s3:GetObject" ], "Effect": "Allow", "Resource": "arn:aws:s3:::eunomia-*" }
        ]
    }
    response = s3.create_bucket(
        ACL='private',
        Bucket="eunomia-"+config["accountid"],
        CreateBucketConfiguration={
            'LocationConstraint': config["region"]
        }
    )
    print "S3 Bucket created at: "+response["Location"]
    response = iam.create_policy(
        PolicyName='eunomia_policy',
        PolicyDocument=json.dumps(policy),
        Description='eunomia execution policy'
    )
    print "Eunomia Policy created at: "+response["Policy"]["Arn"]

def setup_region(config):
    iam = boto3.client('iam')
    sns = boto3.client('sns', region_name=config["region"])
    role_entities = { "Version": "2012-10-17", "Statement": [ { "Action": "sts:AssumeRole", "Effect": "Allow", "Principal": {"Service":[]} } ] }
    entities = ["lambda.amazonaws.com","events.amazonaws.com","states."+config["region"]+".amazonaws.com"]
    role_entities["Statement"][0]["Principal"]["Service"] = entities
    policy_arn = ""
    response = iam.list_policies(
        Scope='Local',
        OnlyAttached=False
    )
    for policy in response["Policies"]:
        if policy["PolicyName"] == "eunomia_policy":
            policy_arn = policy["Arn"]
    response = iam.create_role(
        RoleName="eunomia_execution_role_"+config["region"],
        AssumeRolePolicyDocument=json.dumps(role_entities)
    )
    role_arn = response["Role"]["Arn"]
    print "IAM Role created at: "+role_arn
    response = iam.attach_role_policy(
        RoleName="eunomia_execution_role_"+config["region"],
        PolicyArn=policy_arn
    )
    print "Eunomia Policy attached to Role: "+role_arn
    response = sns.create_topic(
        Name="eunomia_output"
    )
    sns_arn = response["TopicArn"]
    response = sns.set_topic_attributes(
        TopicArn=sns_arn,
        AttributeName='DisplayName',
        AttributeValue='Eunomia'
    )
    print "SNS Topic created at: "+sns_arn
    print "Waiting 10 seconds for role to complete sync..."
    time.sleep(10)
    setup_lambda(config)

def setup_lambda(config):
    if platform.system() != "Linux":
        print "Lambda setup must take place on a Linux device"
        print "Ensure you have installed: gcc libffi-devel python-devel openssl-devel"
        return
    lambda_client = boto3.client('lambda', region_name=config["region"])
    iam = boto3.client('iam')
    role_arn = ""
    roles = iam.list_roles()
    for role in roles["Roles"]:
        if role["RoleName"] == "eunomia_execution_role_"+config["region"]:
            role_arn = role["Arn"]
    if not role_arn:
        print "No valid eunomia role in this region for lambda execution: did you run setup region?"
        sys.exit(1)
    pathname = os.path.dirname(sys.argv[0])
    tmppath = tempfile.mkdtemp()
    subprocess.call(["virtualenv","-p",sys.executable,tmppath])
    activation = tmppath+"/bin/activate_this.py"
    execfile(activation, dict(__file__=activation))
    sys_path = sys.path[0].replace(tmppath+"/lib","")
    subprocess.call(["pip","install","-r", os.path.abspath(pathname)+"/helpers/requirements.txt"])
    list_of_functions = generate_list_of_lambda_functions(config)

    for file in glob.glob(os.path.abspath(pathname)+"/helpers/*"):
        if "eunomia_core.py" in file or "requirements.txt" in file:
            continue
        dir_name = os.path.dirname(file)
        fn_name = os.path.basename(file)
        fn_name = fn_name.replace(".py","")
        shutil.copyfile(file, tmppath+"/lambda.py")
        shutil.copyfile(dir_name+"/eunomia_core.py", tmppath+"/eunomia_core.py")
        zip_file = zipfile.ZipFile(tmppath+"/lambda.zip", 'w', zipfile.ZIP_DEFLATED)
        zip_file.write(tmppath+"/lambda.py", "lambda.py")
        zip_file.write(tmppath+"/eunomia_core.py", "eunomia_core.py")
        for root, dirs, files in os.walk(tmppath+"/lib"+sys_path):
            for file in files:
                zip_root = root.replace(tmppath+"/lib"+sys_path,"")
                zip_file.write(os.path.join(root, file),os.path.join(zip_root, file))
        zip_file.close()
        with open(tmppath+"/lambda.zip", 'rb') as zipf:
            print "Uploading lambda.zip for "+fn_name+"..."
            if fn_name in list_of_functions:
                upload = lambda_client.update_function_code(
                    FunctionName=fn_name,
                    ZipFile=zipf.read(),
                    Publish=True
                )
                print "Lambda Function ("+fn_name+") updated at: "+upload["FunctionArn"]
            else:
                upload = lambda_client.create_function(
                    FunctionName=fn_name,
                    Runtime='python2.7',
                    Role=role_arn,
                    Handler='lambda.lambda_handler',
                    Description="Eunomia Helper: "+fn_name,
                    Timeout=10,
                    MemorySize=128,
                    Publish=True,
                    Code={'ZipFile': zipf.read()},
                )
                print "Lambda Function ("+fn_name+") created at: "+upload["FunctionArn"]
                if fn_name == "eunomia_scheduler":
                    # add additional permissions for cloudwatch events
                    response = lambda_client.add_permission(
                        FunctionName=fn_name,
                        StatementId="AddCWEPermissionsToLambdaFunction",
                        Action="lambda:InvokeFunction",
                        Principal="events.amazonaws.com",
                        SourceArn="arn:aws:events:"+config["region"]+":"+config["accountid"]+":rule/eunomia_*",
                    )
                    print "Lambda Function ("+fn_name+") updated with custom permissions for CloudWatch Events"
                if fn_name == "eunomia_batch_trigger":
                    # create subscription to SNS topic
                    sns = boto3.client('sns', region_name=config["region"])
                    topics = sns.list_topics()
                    for topic in topics["Topics"]:
                        if topic["TopicArn"].endswith(":eunomia_output"):
                            response = lambda_client.add_permission(
                                FunctionName=fn_name,
                                StatementId="AddSNSPermissionsToLambdaFunction",
                                Action="lambda:InvokeFunction",
                                Principal="sns.amazonaws.com",
                                SourceArn=topic["TopicArn"]
                            )
                            print "Lambda Function ("+fn_name+") updated with custom permissions for SNS"
                            response = sns.subscribe(
                                TopicArn=topic["TopicArn"],
                                Protocol='lambda',
                                Endpoint=upload["FunctionArn"]
                            )
                            print "Lambda Function ("+fn_name+") subscribed to: "+topic["TopicArn"]
    shutil.rmtree(tmppath)

def generate_list_of_lambda_functions(config):
    functions = []
    client = boto3.client('lambda', region_name=config["region"])
    response = client.list_functions(
        MaxItems=100
    )
    for func in response["Functions"]:
        if "eunomia_" in func["FunctionName"]:
            functions.append(func["FunctionName"])
    return functions

def secret(config, args):
    if args.type == "add":
        add_secret(config, args)
    elif args.type == "delete":
        delete_secret(config, args)

def add_secret(config, args):
    kms = boto3.client('kms')
    s3 = boto3.resource('s3')
    pad = lambda s: s + (32 - len(s) % 32) * ' '
    if not args.filename and not args.text:
        print "Error: must pass an -f or -t options"
        sys.exit(1)
    if args.filename and args.text:
        print "Error: must choose to pass an -f or -t option, but not both"
        sys.exit(1)
    if args.filename:
        try:
            content = open(args.filename, 'r').read()
        except IOError:
            print "No such file: "+args.filename
            sys.exit(1)
    else:
        content = args.text
    data_key = kms.generate_data_key(
        KeyId="alias/eunomia/secrets",
        KeySpec='AES_256'
    )
    ciphertext_blob = data_key.get('CiphertextBlob')
    plaintext_key = data_key.get('Plaintext')
    crypter = AES.new(plaintext_key, 1)
    encrypted_data = base64.b64encode(crypter.encrypt(pad(content)))
    s3.Bucket("eunomia-"+config["accountid"]).put_object(Key="secrets/"+args.name+"/secret.blob",Body=encrypted_data)
    s3.Bucket("eunomia-"+config["accountid"]).put_object(Key="secrets/"+args.name+"/envelope.key",Body=ciphertext_blob)
    print "Secret successfully saved"

def delete_secret(config, args):
    s3 = boto3.client('s3')
    s3.delete_object(Bucket="eunomia-"+config["accountid"], Key="secrets/"+args.name+"/secret.blob")
    s3.delete_object(Bucket="eunomia-"+config["accountid"], Key="secrets/"+args.name+"/envelope.key")
    print "Secret successfully deleted"

def generate_parse_error(text):
    print "Parse Error: "+text
    return False

def check_validity_of_data(data, list_of_task_types):
    if "name" not in data:
        return generate_parse_error("No name defined")
    if "version" not in data:
        return generate_parse_error("No version defined")
    if "start_at" not in data:
        return generate_parse_error("No starting task defined")
    if "execute" not in data:
        return generate_parse_error("No execution parameters set")
    if "tasks" not in data:
        return generate_parse_error("No tasks defined")
    if data["start_at"] not in data["tasks"]:
        return generate_parse_error("Cannot find a defined starting task")
    for task in data["tasks"]:
        content = data["tasks"][task]
        if " " in task:
            return generate_parse_error(task+" contains space(s) in its name")
        if "type" not in content:
            return generate_parse_error(task+" contains no 'type'")
        if " " in content["type"]:
            return generate_parse_error(task+" has a type containing spaces")
        if content["type"] not in list_of_task_types:
            return generate_parse_error(task+" has invalid type")
        if content["type"] == "custom" and "arn" not in content["options"]:
            return generate_parse_error(task+" has custom type but no associated arn")
        if "output_type" in content and not "output_format" in content:
            return generate_parse_error(task+" has no associated output_format")
        if "output_format" in content and not "output_type" in content:
            return generate_parse_error(task+" has no associated output_type")
        if "output_type" in content and content["output_type"] not in ["json", "text"]:
            return generate_parse_error(task+" has invalid format type")
        if "on_success" in content:
            if content["on_success"] not in data["tasks"]:
                return generate_parse_error(task+" success maps to non-existent task")
        if "on_failure" in content and content["on_failure"] not in data["tasks"]:
            return generate_parse_error(task+" failure state maps to non-existent task")
        if "on_success" not in content and content['type'] != "end":
            return generate_parse_error(task+" has no on_success task")
        if content["type"] == "wait":
            if "time_to_wait" not in content["options"]:
                return generate_parse_error(task+" missing a time_to_wait value")
        if content["type"] == "remote_uri_call":
            if "uri" not in content["options"] or "operation" not in content["options"]:
                return generate_parse_error(task+" has no uri or operation set")
            if content["options"]["operation"] not in ["GET", "POST", "HEAD"]:
                return generate_parse_error(task+" has invalid operation type")
        if content["type"] == "remote_ssh_call":
            if "user" not in content["options"] or "host" not in content["options"] or "secret" not in content["options"] or "command" not in content["options"]:
                return generate_parse_error(task+" is missing user, host, secret, or command")
    return True

def generate_sfn(config, state_machine, task_name, task):
    if task["type"] == "wait":
        return generate_wait_sfn(config, state_machine, task_name, task)
    elif task["type"] == "end":
        return generate_end_sfn(config, state_machine, task_name, task)
    else:
        return generate_task(config, state_machine, task_name, task)

def generate_wait_sfn(config, state_machine, task_name, task):
    state_machine["States"][task_name] = { "Type": "Wait", "Seconds": task["options"]["time_to_wait"], "Next": task["on_success"] }
    return state_machine

def generate_end_sfn(config, state_machine, task_name, task):
    state_machine["States"][task_name] = {
        "Type": "Task",
        "Resource": "arn:aws:lambda:"+config["region"]+":"+config["accountid"]+":function:eunomia_end_task",
        "InputPath": "$",
        "ResultPath": "$",
        "OutputPath": "$",
        "End": True
    }
    return state_machine

def generate_task(config, state_machine, task_name, task):
    state_machine["States"][task_name] = {
        "Type": "Pass",
        "Result": {
            "step": task_name
        },
        "ResultPath": "$.current_step",
        "Next": task_name+"_action"
    }
    arn = "arn:aws:lambda:"+config["region"]+":"+config["accountid"]+":function:eunomia_"+task["type"]
    if task["type"] == "custom":
        arn = task["options"]["arn"]
    state_machine["States"][task_name+"_action"] = {
        "Type": "Task",
        "Resource": arn,
        "InputPath": "$",
        "ResultPath": "$",
        "OutputPath": "$",
        "Next": task["on_success"]
    }
    if "on_failure" in task:
        state_machine["States"][task_name+"_action"]["Catch"] = [{
            "ErrorEquals": [ "States.ALL" ],
            "ResultPath": "$.output."+task_name,
            "Next": task["on_failure"]
        }]
    return state_machine

def update_input_data_set(input_set, task_name, task):
    if task["type"] == "remote_uri_call":
        input_set["input"][task_name] = {'uri': task["options"]["uri"], 'operation': task["options"]["operation"]}
        input_set["output"][task_name] = {}
        if "payload" in task["options"]:
            input_set["input"][task_name]["payload"] = task["options"]["payload"]
        if "output_type" in task["options"] and "output_format" in task["options"]:
            input_set["input"][task_name]["output_type"] = task["options"]["output_type"]
            input_set["input"][task_name]["output_format"] = task["options"]["output_format"]
    elif task["type"] not in ["wait", "end"]:
        input_set["input"][task_name] = {}
        input_set["output"][task_name] = {}
        for key in task["options"]:
            if key not in ["type", "arn", "on_success", "on_failure"]:
                input_set["input"][task_name][key] = task["options"][key]
    return input_set

if __name__ == '__main__':
    main()