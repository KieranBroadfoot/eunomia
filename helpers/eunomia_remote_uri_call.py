import datetime
import json
import urllib2
import cgi
import sys
import re

sys.tracebacklimit = 0

class TaskException(Exception):
    def __init__(self, message, begin, end):
        super(TaskException, self).__init__(message)
        self.args += ('begin_step: '+begin, 'end_step: '+end)

def recurse_object(path, obj):
    element = path.pop(0)
    if len(path) == 0:
        if type(obj[element]) is str or type(obj[element]) is int or type(obj[element]) is unicode:
            return obj[element]
        else:
            return json.dumps(obj[element])
    else:
        return recurse_object(path, obj[element])
    
def lambda_handler(event, context):
    begin_step = str(datetime.datetime.utcnow())
    print event["current_step"]["step"]
    step = event["input"][event["current_step"]["step"]]
    print step
    return_object = { "begin_step": begin_step }
    output = ""
    error_msg = ""
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
        # we have a valid output value, does the user want us to do something with it?
        if "output_format" in step and "output_type" in step:
            if step["output_type"] == "json":
                try:
                    obj = json.loads(output)
                    for key in step["output_format"]:
                        try:
                            if "." in step["output_format"][key]:
                                path = step["output_format"][key].split(".")
                                return_object[key] = recurse_object(path, obj)
                            else:
                                return_object[key] = obj[step["output_format"][key]]
                        except Exception as e:
                            error_msg = "Output does not contain key: "+key
                            raise TaskException
                except ValueError:
                    error_msg = "Output format not JSON"
                    raise TaskException
            if step["output_type"] == "text":
                for key in step["output_format"]:
                    print key
                    try:
                        match = re.search(step["output_format"][key], output)
                        if len(match.groups()) == 0:
                            return_object[key] = match.group().strip()
                        elif len(match.groups()) == 1:
                            return_object[key] = match.group(1).strip()
                        else:
                            for i in range(len(match.groups())):
                                idx = i + 1
                                return_object[key+"_"+str(idx)] = match.group(idx).strip()
                    except Exception as e:
                        print e
                        error_msg = "Output does not contain key: "+key
                        raise TaskException
    except Exception as e:
        if not error_msg:
            error_msg = "Reached an error state."
        raise TaskException(error_msg,begin_step,str(datetime.datetime.utcnow()))
    return_object["end_step"] = str(datetime.datetime.utcnow())
    if "output_type" not in step:
        return_object["raw_output"] = cgi.escape(output)
    event["output"][event["current_step"]["step"]] = return_object
    return event
