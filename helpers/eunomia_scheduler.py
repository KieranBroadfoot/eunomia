from eunomia_core import *

def lambda_handler(event, context):
    batch = EunomiaBatch(account_id=event["account_id"],
                         batch_name=event["batch_name"],
                         batch_path=event["batch_path"],
                         arn=event["batch"])
    return { "execution_arn": batch.execute_batch() }
