"""A set of common tasks for automating interactions with Satellite & Capsule.

Many commands are affected by environment variables. Unless stated otherwise,
all environment variables are required.
"""
import csv
import json
import re
import subprocess
import time

from automation_tools.satellite6.hammer import (
    hammer, set_hammer_config
)
from fabric.api import env, execute, run
from upgrade.helpers.logger import logger

logger = logger()


def reboot(halt_time=300):
    """Reboots the host.

    Also halts the execution until reboots according to given time.

    :param int halt_time: Halt execution in seconds.
    """
    halt_time = halt_time
    logger.info('Rebooting the host, please wait .... ')
    try:
        run('reboot', warn_only=True)
    except:
        pass
    time.sleep(halt_time)


def copy_ssh_key(from_host, to_hosts):
    """This will generate(if not already) ssh-key on from_host
    and copy that ssh-key to to_hosts.

    Beware that to and from hosts should have authorized key added
    for test-running host.

    :param string from_host: Hostname on which the key to be generated and
        to be copied from.
    :param list to_hosts: Hostnames on to which the ssh-key will be copied.

    """
    execute(lambda: run('mkdir -p ~/.ssh'), host=from_host)
    # do we have privkey? generate only pubkey
    execute(lambda: run(
        '[ ! -f ~/.ssh/id_rsa ] || '
        'ssh-keygen -y -f ~/.ssh/id_rsa > ~/.ssh/id_rsa.pub'), host=from_host)
    # dont we have still pubkey? generate keypair
    execute(lambda: run(
        '[ -f ~/.ssh/id_rsa.pub ] || '
        'ssh-keygen -f ~/.ssh/id_rsa -t rsa -N \'\''), host=from_host)
    # read pubkey content in sanitized way
    pub_key = execute(lambda: run(
        '[ ! -f ~/.ssh/id_rsa.pub ] || cat ~/.ssh/id_rsa.pub'),
        host=from_host)[from_host]
    if pub_key:
        for to_host in to_hosts:
            execute(lambda: run('mkdir -p ~/.ssh'), host=to_host)
            # deploy pubkey to another host
            execute(lambda: run(
                'echo "{0}" >> ~/.ssh/authorized_keys'.format(pub_key)
            ), host=to_host)


def host_pings(host, timeout=15):
    """This ensures the given IP/hostname pings succesfully.

    :param host: A string. The IP or hostname of host.
    :param int timeout: The polling timeout in minutes.

    """
    timeup = time.time() + int(timeout) * 60
    while True:
        command = subprocess.Popen(
            'ping -c1 {0}; echo $?'.format(host),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )
        output = command.communicate()[0]
        # Checking the return code of ping is 0
        if time.time() > timeup:
            logger.warning('The timout for pinging the host {0} has '
                           'reached!'.format(host))
            return False
        if int(output.split()[-1]) == 0:
            return True
        else:
            time.sleep(5)


def get_hostname_from_ip(ip, timeout=3):
    """Retrives the hostname by logging into remote machine by IP.
    Specially for the systems who doesnt support reverse DNS.
    e.g usersys machines.

    :param ip: A string. The IP address of the remote host.
    :param int timeout: The polling timeout in minutes.

    """
    timeup = time.time() + int(timeout) * 60
    while True:
        if time.time() > timeup:
            logger.warning(
                'The timeout for getting the Hostname from IP has reached!')
            return False
        try:
            output = execute(lambda: run('hostname'), host=ip)
            logger.info('Hostname determined as: {0}'.format(output[ip]))
            break
        except:
            time.sleep(5)
    return output[ip]


def katello_agent_version_filter(rpm_name):
    """Helper function to filter the katello-agent version from katello-agent
    rpm name

    :param string rpm_name: The katello-agent rpm name
    """
    return re.search('\d(\-\d|\.\d)*', rpm_name).group()


def _extract_sat_cap_version(command):
    """Extracts Satellite and Capsule version

    :param string command: The command to run on Satellite and Capsule that
    returns installed version
    :return string: Satellite/Capsule version
    """
    if command:
        cmd_result = run(command, quiet=True)
        version_re = (
            r'[^\d]*(?P<version>\d(\.\d\.*\d*){1})'
        )
        result = re.search(version_re, cmd_result)
        if result:
            version = result.group('version')
            return version, cmd_result
    return None, cmd_result


def get_sat_cap_version(product):
    """Determines and returns the installed Satellite/Capsule version on system

    :param string product: The product name as satellite/capsule
    :return string: Satellite/Capsule version
    """
    if 'sat' in product.lower():
        _6_2_VERSION_COMMAND = u'rpm -q satellite'
        _LT_6_2_VERSION_COMMAND = (
            u'grep "VERSION" /usr/share/foreman/lib/satellite/version.rb'
        )
    if 'cap' in product.lower():
        _6_2_VERSION_COMMAND = u'rpm -q satellite-capsule'
        _LT_6_2_VERSION_COMMAND = 'None'
    results = (
        _extract_sat_cap_version(cmd) for cmd in
        (_6_2_VERSION_COMMAND, _LT_6_2_VERSION_COMMAND)
    )
    for version, cmd_result in results:
        if version:
            return version
    logger.warning('Unable to detect installed version due to:\n{}'.format(
        cmd_result
    ))


def csv_reader(component, subcommand):
    """
    Reads all component entities data using hammer csv output and returns the
    dict representation of all the entities.

    Representation: {component_name:
    [{comp1_name:comp1, comp1_id:1}, {comp2_name:comp2, comp2_ip:192.168.0.1}]
    }
    e.g:
    {'host':[{name:host1.ab.com, id:10}, {name:host2.xz.com, ip:192.168.0.1}]}

    :param string component: Satellite component name. e.g host, capsule
    :param string subcommand: subcommand for above component. e.g list, info
    :returns dict: The dict repr of hammer csv output of given command
    """
    comp_dict = {}
    entity_list = []
    sat_host = env.get('satellite_host')
    set_hammer_config()
    data = execute(
        hammer, '{0} {1}'.format(component, subcommand), 'csv', host=sat_host
        )[sat_host]
    csv_read = csv.DictReader(str(data.encode('utf-8')).lower().split('\n'))
    for row in csv_read:
        entity_list.append(row)
    comp_dict[component] = entity_list
    return comp_dict


def create_setup_dict(setups_dict):
    """Creates a file to save the return values from setup_products_for_upgrade
     task

    :param string setups_dict: Dictionary of all return value of
    setup_products_for_upgrade
    """
    with open('product_setup', 'wb') as pref:
        json.dump(setups_dict, pref)


def get_setup_data():
    """Open's the file to return the values from
    setup_products_for_upgrade to product_upgrade task
    task

    :returns dict: The dict of all the returns values of
    setup_products_for_upgrade that were saved in the product_setup file
    """
    with open('product_setup', 'r') as pref:
        data = json.load(pref)
    return data