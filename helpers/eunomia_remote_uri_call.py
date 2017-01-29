from eunomia_core import *
import urllib2
import sys

sys.tracebacklimit = 0
    
def lambda_handler(event, context):
    core = EunomiaCore(event)
    step = core.get_step()
    output = ""
    req = urllib2.Request(step["uri"], headers={"User-Agent": "Eunomia"})
    try:
        if step["operation"] == "GET":
            output = urllib2.urlopen(req).read()
        if step["operation"] == "POST":
            req.add_data(step["payload"])
            output = urllib2.urlopen(req).read()
        if step["operation"] == "HEAD":
            req.get_method = lambda : 'HEAD'
            response = urllib2.urlopen(req)
            output = str(response.info())
    except Exception as e:
        raise TaskException("Reached an error state: "+str(e.args[0]),core)
    try:
        core.parse_output(output)
    except:
        raise
    print core.get_event()
    return core.get_event()

if __name__ == '__main__':
    lambda_handler(event, "")