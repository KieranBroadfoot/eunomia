from eunomia_core import *
import boto3
import paramiko
import base64
import StringIO
from Crypto.Cipher import AES
import json

input = '{"batch_name": "eunomia_Test_SSH_v1", "input": {"step_1": {"output_format": {"local": "(10.*)"}, "secret": "my_secret", "host": "brujah.local.", "command": "cat /etc/hosts", "user": "kieran", "output_type": "text"}}, "output": {"step_1": {}}, "current_step":{"step":"step_1"}}'
event = json.loads(input)

def lambda_handler(event, context):
    core = EunomiaCore(event)
    step = core.get_step()

    kms = boto3.client('kms')
    read_s3 = boto3.resource('s3')

    config = {}
    config["accountid"] = boto3.client('sts').get_caller_identity().get('Account')
    session = boto3.session.Session()
    config["region"] = session.region_name

    data = read_s3.Object("eunomia-"+config["accountid"], "secrets/name_of_secret/secret.blob")
    key = read_s3.Object("eunomia-"+config["accountid"], "secrets/name_of_secret/envelope.key")

    decrypted_key = kms.decrypt(CiphertextBlob=key.get()['Body'].read()).get('Plaintext')
    crypter = AES.new(decrypted_key, 1)

    unwrapped_ssh_key = crypter.decrypt(base64.b64decode(data.get()['Body'].read())).rstrip()
    output = StringIO.StringIO(unwrapped_ssh_key)

    k = paramiko.RSAKey.from_private_key(output)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    c.connect( hostname = step["host"], username = step["user"], pkey = k )

    stdin, stdout, stderr = c.exec_command(step["command"])
    output = stderr.read()
    if not output:
        output = stdout.read()
    try:
        core.parse_output(output)
    except:
        raise

    print json.dumps(core.get_event())
    return core.get_event()

if __name__ == '__main__':
    lambda_handler(event, "")