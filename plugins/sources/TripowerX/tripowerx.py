'''
This code is adapted from https://github.com/littleyoda/Home-Assistant-Tripower-X-MQTT
Thank you littleyoda!
'''
import logging
import os
import time
import requests
from utils.smahelpers import unit_of_measurement, isfloat

def env_vars(config):
    if os.environ.get('TRIPOWERX_ENABLED'):
        config['plugin']['enabled'] = os.environ.get('TRIPOWERX_ENABLED')
    if os.environ.get('TRIPOWERX_ADDRESS'):
        config['server']['address'] = os.environ.get('TRIPOWERX_ADDRESS')
    if os.environ.get('TRIPOWERX_USER'):
        config['server']['username'] = os.environ.get('TRIPOWERX_USER')
    if os.environ.get('TRIPOWERX_PASSWORD'):
        config['server']['password'] = os.environ.get('TRIPOWERX_PASSWORD')
    if os.environ.get('TRIPOWERX_UPDATEFREQ'):
        config['server']['updatefreq'] = os.environ.get('TRIPOWERX_UPDATEFREQ')
    if os.environ.get('TRIPOWERX_PREFIX'):
        config['server']['sensorPrefix'] = os.environ.get('TRIPOWERX_PREFIX')

def execute(config, add_data, dostop):
    env_vars(config)

    if config.get('plugin', 'enabled').lower() != 'true':
        logging.info("Tripower X plugin disabled")
        return

    logging.info("Starting Tripower X source")
    loginurl = 'http://' + config.get('server', 'address') + '/api/v1/token'
    postdata = {'grant_type': 'password',
            'username': config.get('server', 'username'),
            'password': config.get('server', 'password'),
            }

    # Login & Extract Access-Token
    try:
        x = requests.post(loginurl, data = postdata, timeout = 5)
    except requests.exceptions.ConnectTimeout:
        logging.fatal("Inverter not reachable via HTTP: " + config.get('server', 'address'))
        return

    if ("Content-Length" in x.headers and x.headers["Content-Length"] == '0'):
        logging.fatal("Username or Password wrong")
        return

    if (404 == x.status_code):
        logging.fatal("HTTP connection to " + config.get('server', 'address') + " refused (status 404)")
        return

    token = x.json()["access_token"] 
    headers = { "Authorization" : "Bearer " + token }

    # Request Device Info
    url = "http://" + config.get('server', 'address') + "/api/v1/plants/Plant:1/devices/IGULD:SELF"
    x = requests.get(url, headers = headers)
    dev = x.json()

    DeviceInfo = {}
    DeviceInfo['name'] = dev["product"]
    DeviceInfo['configuration_url'] = 'http://' + config.get('server', 'address')
    DeviceInfo['identifiers'] = dev["serial"]
    DeviceInfo['model'] = dev["vendor"]+"-" + dev["product"]
    DeviceInfo['manufacturer'] = dev["vendor"]
    DeviceInfo['sw_version'] = dev['firmwareVersion']

    time.sleep(1)

    while not dostop():
        for key, value in DeviceInfo.items(): 
            dname = config.get('server', 'sensorPrefix') + 'device_info.' + key
            logging.debug(dname+': ' + value)
            add_data(dname, value)

        try:
            url = 'http://' + config.get('server', 'address') + '/api/v1/measurements/live'
            x = requests.post(url, headers = headers, data='[{"componentId":"IGULD:SELF"}]')

            # Check if a new acccess token is neccesary (TODO use refresh token)
            if (x.status_code == 401):
                x = requests.post(loginurl, data = postdata)
                token = x.json()["access_token"] 
                headers = { "Authorization" : "Bearer " + token }
                continue
            
            data = x.json()

            for d in data:
                dname = config.get('server', 'sensorPrefix') + d["channelId"].replace("Measurement.","").replace("[]", "")
                if "value" in d["values"][0]:
                    v = d["values"][0]["value"]
                    if isfloat(v):
                        v = round(v,2)
                    unit = unit_of_measurement(dname)

                    logging.debug(dname+': '+str(v)+' '+unit)
                    add_data(dname, v)
                
                elif "values" in d["values"][0]:
                    for idx in range(0, len(d["values"][0]["values"])):
                        v = d["values"][0]["values"][idx]
                        if isfloat(v):
                            v = round(v, 2)
                        idxname = dname + "." + str(idx + 1)
                        unit = unit_of_measurement(dname)

                        logging.debug(idxname+': '+str(v)+' '+unit)
                        add_data(idxname, v)
                
                else:
                    logging.debug("value currently not availably (nighttime?)")
                    pass

            time.sleep(int(config.get('server', 'updatefreq')))
        except TimeoutError:
            pass

    logging.info("Stopping Tripower X source")