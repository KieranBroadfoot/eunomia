import datetime
import json
import re
import cgi

class EunomiaCore:

    _event = {}
    _step = {}
    _output = {}
    _begin_step = str(datetime.datetime.utcnow())

    def __init__(self, event):
        self._event = event
        self._step = self._event["input"][self._event["current_step"]["step"]]

    def get_step(self):
        return self._step

    def get_start_timestamp(self):
        return self._begin_step

    def get_account_id(self):
        return self._event["account_id"]

    def set_output_kv(self, key, value):
        self._event["output"][key] = value

    def get_event(self):
        self._step["begin_step"] = self._begin_step
        self._step["end_step"] = str(datetime.datetime.utcnow())
        self._event["output"][self._event["current_step"]["step"]] = self._output
        return self._event

    def recurse_object(self, path, obj):
        element = path.pop(0)
        if len(path) == 0:
            if type(obj[element]) is str or type(obj[element]) is int or type(obj[element]) is unicode:
                return obj[element]
            else:
                return json.dumps(obj[element])
        else:
            return recurse_object(path, obj[element])

    def parse_output(self, output):
        if "output_format" in self._step and "output_type" in self._step:
            if self._step["output_type"] == "json":
                try:
                    obj = json.loads(output)
                    for key in self._step["output_format"]:
                        try:
                            if "." in self._step["output_format"][key]:
                                path = self._step["output_format"][key].split(".")
                                self._output[key] = self.recurse_object(path, obj)
                            else:
                                self._output[key] = obj[self._step["output_format"][key]]
                        except Exception as e:
                            raise TaskException("Output does not contain key: "+key,self)
                except ValueError:
                    raise TaskException("Output format not JSON",self)
            if self._step["output_type"] == "text":
                for key in self._step["output_format"]:
                    try:
                        match = re.search(self._step["output_format"][key], output)
                        if len(match.groups()) == 0:
                            self._output[key] = match.group().strip()
                        elif len(match.groups()) == 1:
                            self._output[key] = match.group(1).strip()
                        else:
                            for i in range(len(match.groups())):
                                idx = i + 1
                                self._output[key+"_"+str(idx)] = match.group(idx).strip()
                    except Exception as e:
                        raise TaskException("Output does not contain key: "+key,self)
        if "output_type" not in self._step:
            self._step["raw_output"] = cgi.escape(output)

class TaskException(Exception):
    def __init__(self, message, core_object):
        super(TaskException, self).__init__(message)
        self.args += ('begin_step: '+core_object.get_start_timestamp(), 'end_step: '+str(datetime.datetime.utcnow()))