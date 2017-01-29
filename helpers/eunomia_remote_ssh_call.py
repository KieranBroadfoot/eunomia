from eunomia_core import *
import boto3
import paramiko
import base64
import StringIO
from Crypto.Cipher import AES
import json

kms = boto3.client('kms')

def lambda_handler(event, context):
    core = EunomiaCore(event)
    step = core.get_step()

    account_id = core.get_account_id()
    data = helper_get_s3_object(account_id=account_id, path="secrets/"+step["secret"]+"/secret.blob")
    key = helper_get_s3_object(account_id=account_id, path="secrets/"+step["secret"]+"/envelope.key")

    try:
        decrypted_key = kms.decrypt(CiphertextBlob=key.get()['Body'].read()).get('Plaintext')
    except Exception as e:
        raise TaskException("No Secret: "+str(e.args[0]),core)
    crypter = AES.new(decrypted_key, 1)

    unwrapped_ssh_key = crypter.decrypt(base64.b64decode(data.get()['Body'].read())).rstrip()
    output = StringIO.StringIO(unwrapped_ssh_key)

    try:
        ssh_private_key = paramiko.RSAKey.from_private_key(output)
    except Exception as e:
        raise TaskException("Issue with SSH Key: "+str(e.args[0]),core)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect( hostname = step["host"], username = step["user"], pkey = ssh_private_key )
    except Exception as e:
        raise TaskException("SSH Connection Error: "+str(e.args[0]),core)

    stdin, stdout, stderr = client.exec_command(step["command"])
    output = stderr.read()
    if not output:
        output = stdout.read()
    try:
        core.parse_output(output)
    except:
        raise

    print json.dumps(core.get_event())
    return core.get_event()