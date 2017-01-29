from eunomia_core import *
import boto3

def lambda_handler(event, context):
    core = EunomiaCore(event)
    step = core.get_step()

    name = step["name"].replace(" ","_")
    version = str(step["version"])
    if not version.startswith("v"):
        version = "v"+version
    full_name = "eunomia_"+name+"_"+version
    path = "batch/"+name+"/"+version
    arn = "unknown"

    client = boto3.client('stepfunctions')
    response = client.list_state_machines()

    for sfn in response["stateMachines"]:
        if sfn["name"] == full_name:
            arn = sfn["stateMachineArn"]

    batch = EunomiaBatch(account_id=core.get_account_id(),
                         batch_name=full_name,
                         batch_path=path,
                         arn=arn)

    core.set_output_kv("batch_arn", batch.execute_batch())

    return core.get_event()
