# -*- coding: utf-8 -*-
'''
Connection module for Amazon EC2

.. versionadded:: 2015.8.0

:configuration: This module accepts explicit EC2 credentials but can also
    utilize IAM roles assigned to the instance trough Instance Profiles.
    Dynamic credentials are then automatically obtained from AWS API and no
    further configuration is necessary. More Information available at:

    .. code-block:: text

        http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html

    If IAM roles are not used you need to specify them either in a pillar or
    in the minion's config file:

    .. code-block:: yaml

        ec2.keyid: GKTADJGHEIQSXMKKRBJ08H
        ec2.key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs

    A region may also be specified in the configuration:

    .. code-block:: yaml

        ec2.region: us-east-1

    If a region is not specified, the default is us-east-1.

    It's also possible to specify key, keyid and region via a profile, either
    as a passed in dict, or as a string to pull from pillars or minion config:

    .. code-block:: yaml

        myprofile:
            keyid: GKTADJGHEIQSXMKKRBJ08H
            key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs
            region: us-east-1

:depends: boto

'''
# keep lint from choking on _get_conn and _cache_id
#pylint: disable=E0602

# Import Python libs
from __future__ import absolute_import
import logging
import time
from distutils.version import LooseVersion as _LooseVersion  # pylint: disable=import-error,no-name-in-module

# Import Salt libs
import salt.utils
import salt.utils.compat
import salt.ext.six as six
from salt.exceptions import SaltInvocationError, CommandExecutionError

# Import third party libs
try:
    # pylint: disable=unused-import
    import boto
    import boto.ec2
    # pylint: enable=unused-import
    HAS_BOTO = True
except ImportError:
    HAS_BOTO = False


log = logging.getLogger(__name__)


def __virtual__():
    '''
    Only load if boto libraries exist and if boto libraries are greater than
    a given version.
    '''
    required_boto_version = '2.8.0'
    # the boto_ec2 execution module relies on the connect_to_region() method
    # which was added in boto 2.8.0
    # https://github.com/boto/boto/commit/33ac26b416fbb48a60602542b4ce15dcc7029f12
    if not HAS_BOTO:
        return (False, "The boto_ec2 module cannot be loaded: boto library not found")
    elif _LooseVersion(boto.__version__) < _LooseVersion(required_boto_version):
        return (False, "The boto_ec2 module cannot be loaded: boto library version incorrect ")
    return True


def __init__(opts):
    salt.utils.compat.pack_dunder(__name__)
    if HAS_BOTO:
        __utils__['boto.assign_funcs'](__name__, 'ec2')


def _get_all_eip_addresses(addresses=None, allocation_ids=None, region=None,
                           key=None, keyid=None, profile=None):
    '''
    Get all EIP's associated with the current credentials.

    addresses
        (list) - Optional list of addresses.  If provided, only those those in the
        list will be returned.
    allocation_ids
        (list) - Optional list of allocation IDs.  If provided, only the
        addresses associated with the given allocation IDs will be returned.

    returns
        (list) - The requested Addresses as a list of :class:`boto.ec2.address.Address`
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        return conn.get_all_addresses(addresses=addresses, allocation_ids=allocation_ids)
    except boto.exception.BotoServerError as e:
        log.error(e)
        return []


def get_all_eip_addresses(addresses=None, allocation_ids=None, region=None,
                           key=None, keyid=None, profile=None):
    '''
    Get public addresses of some, or all EIPs associated with the current account.

    addresses
        (list) - Optional list of addresses.  If provided, only the addresses
        associated with those in the list will be returned.
    allocation_ids
        (list) - Optional list of allocation IDs.  If provided, only the
        addresses associated with the given allocation IDs will be returned.

    returns
        (list) - A list of the requested EIP addresses

    CLI Example:

    .. code-block:: bash

        salt-call boto_ec2.get_all_eip_addresses

    .. versionadded:: Boron
    '''
    return [x.public_ip for x in _get_all_eip_addresses(addresses, allocation_ids, region,
                key, keyid, profile)]


def get_unassociated_eip_address(domain='standard', region=None, key=None,
                                 keyid=None, profile=None):
    '''
    Return the first unassociated EIP

    domain
        Indicates whether the address is a EC2 address or a VPC address
        (standard|vpc).

    CLI Example:

    .. code-block:: bash

        salt-call boto_ec2.get_unassociated_eip_address

    .. versionadded:: Boron
    '''
    eip = None
    for address in get_all_eip_addresses(region=region, key=key, keyid=keyid,
                                         profile=profile):
        address_info = get_eip_address_info(addresses=address, region=region,
                                            key=key, keyid=keyid,
                                            profile=profile)[0]
        if address_info['instance_id']:
            log.debug('{0} is already associated with the instance {1}'.format(
                address, address_info['instance_id']))
            continue

        if address_info['network_interface_id']:
            log.debug('{0} is already associated with the network interface {1}'
                      .format(address, address_info['network_interface_id']))
            continue

        if address_info['domain'] == domain:
            log.debug("The first unassociated EIP address in the domain '{0}' "
                      "is {1}".format(domain, address))
            eip = address
            break

    if not eip:
        log.debug('No unassociated Elastic IP found!')

    return eip


def get_eip_address_info(addresses=None, allocation_ids=None, region=None, key=None,
                         keyid=None, profile=None):
    '''
    Get 'interesting' info about some, or all EIPs associated with the current account.

    addresses
        (list) - Optional list of addresses.  If provided, only the addresses
        associated with those in the list will be returned.
    allocation_ids
        (list) - Optional list of allocation IDs.  If provided, only the
        addresses associated with the given allocation IDs will be returned.

    returns
        (list of dicts) - A list of dicts, each containing the info for one of the requested EIPs.

    CLI Example:

    .. code-block:: bash

        salt-call boto_ec2.get_eip_address_info addresses=52.4.2.15

    .. versionadded:: Boron
    '''
    if type(addresses) == (type('string')):
        addresses = [addresses]
    if type(allocation_ids) == (type('string')):
        allocation_ids = [allocation_ids]

    ret = _get_all_eip_addresses(addresses=addresses, allocation_ids=allocation_ids,
                       region=region, key=key, keyid=keyid, profile=profile)

    interesting = ['allocation_id', 'association_id', 'domain', 'instance_id',
                   'network_interface_id', 'network_interface_owner_id', 'public_ip',
                   'private_ip_address']

    return [dict([(x, getattr(address, x)) for x in interesting]) for address in ret]


def allocate_eip_address(domain=None, region=None, key=None, keyid=None, profile=None):
    '''
    Allocate a new Elastic IP address and associate it with your account.

    domain
        (string) Optional param - if set to exactly 'vpc', the address will be
        allocated to the VPC.  The default simply maps the EIP to your
        account container.

    returns
        (dict) dict of 'interesting' information about the newly allocated EIP,
        with probably the most interesting keys being 'public_ip'; and
        'allocation_id' iff 'domain=vpc' was passed.

    CLI Example:

    .. code-block:: bash

        salt-call boto_ec2.allocate_eip_address domain=vpc

    .. versionadded:: Boron
    '''
    if domain and domain != 'vpc':
        raise SaltInvocationError('The only permitted value for the \'domain\' param is \'vpc\'.')

    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        address = conn.allocate_address(domain=domain)
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False

    interesting = ['allocation_id', 'association_id', 'domain', 'instance_id',
                   'network_interface_id', 'network_interface_owner_id', 'public_ip',
                   'private_ip_address']

    return dict([(x, getattr(address, x)) for x in interesting])


def release_eip_address(public_ip=None, allocation_id=None, region=None, key=None,
                        keyid=None, profile=None):
    '''
    Free an Elastic IP address.  Pass either a public IP address to release a 'standard'
    EC2 Elastic IP address, or an AllocationId to release a VPC Elastic IP address.

    public_ip
        (string) - The public IP address - for EC2 elastic IPs.
    allocation_id
        (string) - The Allocation ID - for VPC elastic IPs.

    returns
        (bool) - True on success, False on failure

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.release_eip_address allocation_id=eipalloc-ef382c8a

    .. versionadded:: Boron
    '''
    if not salt.utils.exactly_one((public_ip, allocation_id)):
        raise SaltInvocationError('Exactly one (but not both) of \'public_ip\' '
                                  'or \'allocation_id\' must be provided')

    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        return conn.release_address(public_ip, allocation_id)
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def associate_eip_address(instance_id=None, instance_name=None, public_ip=None,
                          allocation_id=None, network_interface_id=None,
                          network_interface_name=None, private_ip_address=None,
                          allow_reassociation=False, region=None, key=None,
                          keyid=None, profile=None):
    '''
    Associate an Elastic IP address with a currently running instance or a network interface.
    This requires exactly one of either 'public_ip' or 'allocation_id', depending
    on whether you’re associating a VPC address or a plain EC2 address.

    instance_id
        (string) – ID of the instance to associate with (exclusive with 'instance_name')
    instance_name
        (string) – Name tag of the instance to associate with (exclusive with 'instance_id')
    public_ip
        (string) – Public IP address, for standard EC2 based allocations.
    allocation_id
        (string) – Allocation ID for a VPC-based EIP.
    network_interface_id
        (string) - ID of the network interface to associate the EIP with
    network_interface_name
        (string) - Name of the network interface to associate the EIP with
    private_ip_address
        (string) – The primary or secondary private IP address to associate with the Elastic IP address.
    allow_reassociation
        (bool)   – Allow a currently associated EIP to be re-associated with the new instance or interface.

    returns
        (bool)   - True on success, False otherwise

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.associate_eip_address instance_name=bubba.ho.tep allocation_id=eipalloc-ef382c8a

    .. versionadded:: Boron
    '''
    if not salt.utils.exactly_one((instance_id, instance_name,
                                   network_interface_id,
                                   network_interface_name)):
        raise SaltInvocationError("Exactly one of 'instance_id', "
                                  "'instance_name', 'network_interface_id', "
                                  "'network_interface_name' must be provided")

    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    if instance_name:
        try:
            instance_id = get_id(name=instance_name, region=region, key=key,
                                 keyid=keyid, profile=profile)
        except boto.exception.BotoServerError as e:
            log.error(e)
            return False
        if not instance_id:
            log.error("Given instance_name '{0}' cannot be mapped to an "
                      "instance_id".format(instance_name))
            return False

    if network_interface_name:
        try:
            network_interface_id = get_network_interface_id(
                network_interface_name, region=region, key=key, keyid=keyid,
                profile=profile)
        except boto.exception.BotoServerError as e:
            log.error(e)
            return False
        if not network_interface_id:
            log.error("Given network_interface_name '{0}' cannot be mapped to "
                      "an network_interface_id".format(network_interface_name))
            return False

    try:
        return conn.associate_address(instance_id=instance_id, public_ip=public_ip,
              allocation_id=allocation_id, network_interface_id=network_interface_id,
              private_ip_address=private_ip_address, allow_reassociation=allow_reassociation)
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def disassociate_eip_address(public_ip=None, association_id=None, region=None,
                             key=None, keyid=None, profile=None):
    '''
    Disassociate an Elastic IP address from a currently running instance. This
    requires exactly one of either 'association_id' or 'public_ip', depending
    on whether you’re associating a VPC address or a plain EC2 address.

    public_ip
        (string) – Public IP address, for standard EC2 based allocations.
    association_id
        (string) – Association ID for a VPC-based EIP.

    returns
        (bool)   - True on success, False otherwise

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.disassociate_eip_address association_id=eipassoc-e3ba2d16

    .. versionadded:: Boron
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        return conn.disassociate_address(public_ip, association_id)
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def get_zones(region=None, key=None, keyid=None, profile=None):
    '''
    Get a list of AZs for the configured region.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.get_zones
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    return [z.name for z in conn.get_all_zones()]


def find_instances(instance_id=None, name=None, tags=None, region=None,
                   key=None, keyid=None, profile=None, return_objs=False,
                   in_states=None):

    '''
    Given instance properties, find and return matching instance ids

    CLI Examples:

    .. code-block:: bash

        salt myminion boto_ec2.find_instances # Lists all instances
        salt myminion boto_ec2.find_instances name=myinstance
        salt myminion boto_ec2.find_instances tags='{"mytag": "value"}'

    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    if not any((instance_id, name, tags)):
        return []
    try:
        filter_parameters = {'filters': {}}

        if instance_id:
            filter_parameters['instance_ids'] = [instance_id]

        if name:
            filter_parameters['filters']['tag:Name'] = name

        if tags:
            for tag_name, tag_value in six.iteritems(tags):
                filter_parameters['filters']['tag:{0}'.format(tag_name)] = tag_value

        reservations = conn.get_all_instances(**filter_parameters)
        instances = [i for r in reservations for i in r.instances]
        log.debug('The filters criteria {0} matched the following '
                  'instances:{1}'.format(filter_parameters, instances))

        if in_states:
            instances = [i for i in instances if i.state in in_states]
            log.debug('Limiting instance matches to those in the requested '
                      'states: {0}'.format(instances))
        if instances:
            if return_objs:
                return instances
            return [instance.id for instance in instances]
        else:
            return []
    except boto.exception.BotoServerError as exc:
        log.error(exc)
        return []


def create_image(ami_name, instance_id=None, instance_name=None, tags=None, region=None,
                 key=None, keyid=None, profile=None, description=None, no_reboot=False,
                 dry_run=False):
    '''
    Given instance properties that define exactly one instance, create AMI and return AMI-id.

    CLI Examples:

    .. code-block:: bash

        salt myminion boto_ec2.create_instance ami_name instance_name=myinstance
        salt myminion boto_ec2.create_instance another_ami_name tags='{"mytag": "value"}' description='this is my ami'

    '''

    instances = find_instances(instance_id=instance_id, name=instance_name, tags=tags,
                               region=region, key=key, keyid=keyid, profile=profile,
                               return_objs=True)

    if not instances:
        log.error('Source instance not found')
        return False
    if len(instances) > 1:
        log.error('Multiple instances found, must match exactly only one instance to create an image from')
        return False

    instance = instances[0]
    try:
        return instance.create_image(ami_name, description=description,
                                     no_reboot=no_reboot, dry_run=dry_run)
    except boto.exception.BotoServerError as exc:
        log.error(exc)
        return False


def find_images(ami_name=None, executable_by=None, owners=None, image_ids=None, tags=None,
                region=None, key=None, keyid=None, profile=None, return_objs=False):

    '''
    Given image properties, find and return matching AMI ids

    CLI Examples:

    .. code-block:: bash

        salt myminion boto_ec2.find_instances tags='{"mytag": "value"}'

    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        filter_parameters = {'filters': {}}

        if image_ids:
            filter_parameters['image_ids'] = [image_ids]

        if executable_by:
            filter_parameters['executable_by'] = [executable_by]

        if owners:
            filter_parameters['owners'] = [owners]

        if ami_name:
            filter_parameters['filters']['name'] = ami_name

        if tags:
            for tag_name, tag_value in six.iteritems(tags):
                filter_parameters['filters']['tag:{0}'.format(tag_name)] = tag_value

        images = conn.get_all_images(**filter_parameters)
        log.debug('The filters criteria {0} matched the following '
                  'images:{1}'.format(filter_parameters, images))

        if images:
            if return_objs:
                return images
            return [image.id for image in images]
        else:
            return False
    except boto.exception.BotoServerError as exc:
        log.error(exc)
        return False


def terminate(instance_id=None, name=None, region=None,
              key=None, keyid=None, profile=None):
    '''
    Terminate the instance described by instance_id or name.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.terminate name=myinstance
        salt myminion boto_ec2.terminate instance_id=i-a46b9f
    '''
    instances = find_instances(instance_id=instance_id, name=name,
                               region=region, key=key, keyid=keyid,
                               profile=profile, return_objs=True)
    if instances in (False, None, []):
        return instances

    if len(instances) == 1:
        instances[0].terminate()
        return True
    else:
        log.warning('Refusing to terminate multiple instances at once')
        return False


def get_id(name=None, tags=None, region=None, key=None,
           keyid=None, profile=None, in_states=None):

    '''
    Given instace properties, return the instance id if it exist.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.get_id myinstance

    '''
    instance_ids = find_instances(name=name, tags=tags, region=region, key=key,
                                  keyid=keyid, profile=profile, in_states=in_states)
    if instance_ids:
        log.info("Instance ids: {0}".format(" ".join(instance_ids)))
        if len(instance_ids) == 1:
            return instance_ids[0]
        else:
            raise CommandExecutionError('Found more than one instance '
                                        'matching the criteria.')
    else:
        log.warning('Could not find instance.')
        return None


def exists(instance_id=None, name=None, tags=None, region=None, key=None,
           keyid=None, profile=None, in_states=None):
    '''
    Given a instance id, check to see if the given instance id exists.

    Returns True if the given an instance with the given id, name, or tags
    exists; otherwise, False is returned.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.exists myinstance
    '''
    instances = find_instances(instance_id=instance_id, name=name, tags=tags,
                               region=region, key=key, keyid=keyid,
                               profile=profile, in_states=in_states)
    if instances:
        log.info('Instance exists.')
        return True
    else:
        log.warning('Instance does not exist.')
        return False


def run(image_id, name=None, tags=None, key_name=None, security_groups=None,
        user_data=None, instance_type='m1.small', placement=None,
        kernel_id=None, ramdisk_id=None, monitoring_enabled=None, vpc_id=None,
        vpc_name=None, subnet_id=None, subnet_name=None, private_ip_address=None,
        block_device_map=None, disable_api_termination=None,
        instance_initiated_shutdown_behavior=None, placement_group=None,
        client_token=None, security_group_ids=None, security_group_names=None,
        additional_info=None, tenancy=None, instance_profile_arn=None,
        instance_profile_name=None, ebs_optimized=None,
        network_interface_id=None, network_interface_name=None,
        region=None, key=None, keyid=None, profile=None, network_interfaces=None):
    #TODO: support multi-instance reservations
    '''
    Create and start an EC2 instance.

    Returns True if the instance was created; otherwise False.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.run ami-b80c2b87 name=myinstance

    image_id
        (string) – The ID of the image to run.
    name
        (string) - The name of the instance.
    tags
        (dict of key: value pairs) - tags to apply to the instance.
    key_name
        (string) – The name of the key pair with which to launch instances.
    security_groups
        (list of strings) – The names of the EC2 classic security groups with
        which to associate instances
    user_data
        (string) – The Base64-encoded MIME user data to be made available to the
        instance(s) in this reservation.
    instance_type
        (string) – The type of instance to run.  Note that some image types
        (e.g. hvm) only run on some instance types.
    placement
        (string) – The Availability Zone to launch the instance into.
    kernel_id
        (string) – The ID of the kernel with which to launch the instances.
    ramdisk_id
        (string) – The ID of the RAM disk with which to launch the instances.
    monitoring_enabled
        (bool) – Enable detailed CloudWatch monitoring on the instance.
    vpc_id
        (string) - ID of a VPC to bind the instance to.  Exclusive with vpc_name.
    vpc_name
        (string) - Name of a VPC to bind the instance to.  Exclusive with vpc_id.
    subnet_id
        (string) – The subnet ID within which to launch the instances for VPC.
    subnet_name
        (string) – The name of a subnet within which to launch the instances for VPC.
    private_ip_address
        (string) – If you’re using VPC, you can optionally use this parameter to
        assign the instance a specific available IP address from the subnet
        (e.g. 10.0.0.25).
    block_device_map
        (boto.ec2.blockdevicemapping.BlockDeviceMapping) – A BlockDeviceMapping
        data structure describing the EBS volumes associated with the Image.
    disable_api_termination
        (bool) – If True, the instances will be locked and will not be able to
        be terminated via the API.
    instance_initiated_shutdown_behavior
        (string) – Specifies whether the instance stops or terminates on
        instance-initiated shutdown. Valid values are: stop, terminate
    placement_group
        (string) – If specified, this is the name of the placement group in
        which the instance(s) will be launched.
    client_token
        (string) – Unique, case-sensitive identifier you provide to ensure
        idempotency of the request. Maximum 64 ASCII characters.
    security_group_ids
        (list of strings) – The ID(s) of the VPC security groups with which to
        associate instances.
    security_group_names
        (list of strings) – The name(s) of the VPC security groups with which to
        associate instances.
    additional_info
        (string) – Specifies additional information to make available to the
        instance(s).
    tenancy
        (string) – The tenancy of the instance you want to launch. An instance
        with a tenancy of ‘dedicated’ runs on single-tenant hardware and can
        only be launched into a VPC. Valid values are:”default” or “dedicated”.
        NOTE: To use dedicated tenancy you MUST specify a VPC subnet-ID as well.
    instance_profile_arn
        (string) – The Amazon resource name (ARN) of the IAM Instance Profile
        (IIP) to associate with the instances.
    instance_profile_name
        (string) – The name of the IAM Instance Profile (IIP) to associate with
        the instances.
    ebs_optimized
        (bool) – Whether the instance is optimized for EBS I/O. This
        optimization provides dedicated throughput to Amazon EBS and an
        optimized configuration stack to provide optimal EBS I/O performance.
        This optimization isn’t available with all instance types.
    network_interfaces
        (boto.ec2.networkinterface.NetworkInterfaceCollection) – A
        NetworkInterfaceCollection data structure containing the ENI
        specifications for the instance.
    network_interface_id
        (string) - ID of the network interface to attach to the instance
    network_interface_name
        (string) - Name of the network interface to attach to the instance

    '''
    if all((subnet_id, subnet_name)):
        raise SaltInvocationError('Only one of subnet_name or subnet_id may be '
                                  'provided.')
    if subnet_name:
        r = __salt__['boto_vpc.get_resource_id']('subnet', subnet_name,
                                                 region=region, key=key,
                                                 keyid=keyid, profile=profile)
        if 'id' not in r:
            log.warning('Couldn\'t resolve subnet name {0}.').format(subnet_name)
            return False
        subnet_id = r['id']

    if all((security_group_ids, security_group_names)):
        raise SaltInvocationError('Only one of security_group_ids or '
                                  'security_group_names may be provided.')
    if security_group_names:
        security_group_ids = []
        for sgn in security_group_names:
            r = __salt__['boto_secgroup.get_group_id'](sgn, vpc_name=vpc_name,
                                                       region=region, key=key,
                                                       keyid=keyid, profile=profile)
            if not r:
                log.warning('Couldn\'t resolve security group name ' + str(sgn))
                return False
            security_group_ids += [r]

    if all((network_interface_id, network_interface_name)):
        raise SaltInvocationError('Only one of network_interface_id or '
                                  'network_interface_name may be provided.')
    if network_interface_name:
        network_interface_id = get_network_interface_id(network_interface_name,
                                                        region=region, key=key,
                                                        keyid=keyid,
                                                        profile=profile)
        if not network_interface_id:
            log.warning(
                "Given network_interface_name '{0}' cannot be mapped to an "
                "network_interface_id".format(network_interface_name)
            )

    if network_interface_id:
        interface = boto.ec2.networkinterface.NetworkInterfaceSpecification(
            network_interface_id=network_interface_id,
            device_index=0
        )
    else:
        interface = boto.ec2.networkinterface.NetworkInterfaceSpecification(
            subnet_id=subnet_id,
            groups=security_group_ids,
            device_index=0
        )
    interfaces = boto.ec2.networkinterface.NetworkInterfaceCollection(interface)

    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    reservation = conn.run_instances(image_id, key_name=key_name, security_groups=security_groups,
                                     user_data=user_data, instance_type=instance_type,
                                     placement=placement, kernel_id=kernel_id, ramdisk_id=ramdisk_id,
                                     monitoring_enabled=monitoring_enabled,
                                     private_ip_address=private_ip_address, block_device_map=block_device_map,
                                     disable_api_termination=disable_api_termination,
                                     instance_initiated_shutdown_behavior=instance_initiated_shutdown_behavior,
                                     placement_group=placement_group, client_token=client_token,
                                     additional_info=additional_info,
                                     tenancy=tenancy, instance_profile_arn=instance_profile_arn,
                                     instance_profile_name=instance_profile_name, ebs_optimized=ebs_optimized,
                                     network_interfaces=interfaces)
    if not reservation:
        log.warning('Instance could not be reserved')
        return False

    instance = reservation.instances[0]

    status = 'pending'
    while status == 'pending':
        time.sleep(5)
        status = instance.update()
    if status == 'running':
        if name:
            instance.add_tag('Name', name)
        if tags:
            instance.add_tags(tags)
        return {'instance_id': instance.id}
    else:
        log.warning('Instance could not be started -- '
                    'status is "{0}"'.format(status))


def get_key(key_name, region=None, key=None, keyid=None, profile=None):
    '''
    Check to see if a key exists. Returns fingerprint and name if
    it does and False if it doesn't
    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.get_key mykey
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        key = conn.get_key_pair(key_name)
        log.debug("the key to return is : {0}".format(key))
        if key is None:
            return False
        return key.name, key.fingerprint
    except boto.exception.BotoServerError as e:
        log.debug(e)
        return False


def create_key(key_name, save_path, region=None, key=None, keyid=None,
               profile=None):
    '''
    Creates a key and saves it to a given path.
    Returns the private key.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.create mykey /root/
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        key = conn.create_key_pair(key_name)
        log.debug("the key to return is : {0}".format(key))
        key.save(save_path)
        return key.material
    except boto.exception.BotoServerError as e:
        log.debug(e)
        return False


def import_key(key_name, public_key_material, region=None, key=None,
               keyid=None, profile=None):
    '''
    Imports the public key from an RSA key pair that you created with a third-party tool.
    Supported formats:
    - OpenSSH public key format (e.g., the format in ~/.ssh/authorized_keys)
    - Base64 encoded DER format
    - SSH public key file format as specified in RFC4716
    - DSA keys are not supported. Make sure your key generator is set up to create RSA keys.
    Supported lengths: 1024, 2048, and 4096.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.import mykey publickey
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        key = conn.import_key_pair(key_name, public_key_material)
        log.debug("the key to return is : {0}".format(key))
        return key.fingerprint
    except boto.exception.BotoServerError as e:
        log.debug(e)
        return False


def delete_key(key_name, region=None, key=None, keyid=None, profile=None):
    '''
    Deletes a key. Always returns True

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.delete_key mykey
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        key = conn.delete_key_pair(key_name)
        log.debug("the key to return is : {0}".format(key))
        return key
    except boto.exception.BotoServerError as e:
        log.debug(e)
        return False


def get_keys(keynames=None, filters=None, region=None, key=None,
             keyid=None, profile=None):
    '''
    Gets all keys or filters them by name and returns a list.
    keynames (list):: A list of the names of keypairs to retrieve.
    If not provided, all key pairs will be returned.
    filters (dict) :: Optional filters that can be used to limit the
    results returned. Filters are provided in the form of a dictionary
    consisting of filter names as the key and filter values as the
    value. The set of allowable filter names/values is dependent on
    the request being performed. Check the EC2 API guide for details.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.get_keys
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    try:
        keys = conn.get_all_key_pairs(keynames, filters)
        log.debug("the key to return is : {0}".format(keys))
        key_values = []
        if keys:
            for key in keys:
                key_values.append(key.name)
        return key_values
    except boto.exception.BotoServerError as e:
        log.debug(e)
        return False


def get_attribute(attribute, instance_name=None, instance_id=None, region=None, key=None,
                  keyid=None, profile=None):
    '''
    Get an EC2 instance attribute.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.get_attribute name=my_instance attribute=sourceDestCheck

    Available attributes:
        * instanceType
        * kernel
        * ramdisk
        * userData
        * disableApiTermination
        * instanceInitiatedShutdownBehavior
        * rootDeviceName
        * blockDeviceMapping
        * productCodes
        * sourceDestCheck
        * groupSet
        * ebsOptimized
        * sriovNetSupport
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    attribute_list = ['instanceType', 'kernel', 'ramdisk', 'userData', 'disableApiTermination',
                      'instanceInitiatedShutdownBehavior', 'rootDeviceName', 'blockDeviceMapping', 'productCodes',
                      'sourceDestCheck', 'groupSet', 'ebsOptimized', 'sriovNetSupport']
    if not any((instance_name, instance_id)):
        raise SaltInvocationError('At least one of the following must be specified: '
                                  'instance_name or instance_id.')
    if instance_name and instance_id:
        raise SaltInvocationError('Both instance_name and instance_id can not be specified in the same command.')
    if attribute not in attribute_list:
        raise SaltInvocationError('Attribute must be one of: {0}.'.format(attribute_list))
    try:
        if instance_name:
            instances = find_instances(name=instance_name, region=region, key=key, keyid=keyid, profile=profile)
            if len(instances) > 1:
                log.error('Found more than one EC2 instance matching the criteria.')
                return False
            elif len(instances) < 1:
                log.error('Found no EC2 instance matching the criteria.')
                return False
            instance_id = instances[0]
        instance_attribute = conn.get_instance_attribute(instance_id, attribute)
        if not instance_attribute:
            return False
        return {attribute: instance_attribute[attribute]}
    except boto.exception.BotoServerError as exc:
        log.error(exc)
        return False


def set_attribute(attribute, attribute_value, instance_name=None, instance_id=None, region=None, key=None, keyid=None,
                  profile=None):
    '''
    Set an EC2 instance attribute.
    Returns whether the operation succeeded or not.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.set_attribute instance_name=my_instance \
                attribute=sourceDestCheck attribute_value=False

    Available attributes:
        * instanceType
        * kernel
        * ramdisk
        * userData
        * disableApiTermination
        * instanceInitiatedShutdownBehavior
        * rootDeviceName
        * blockDeviceMapping
        * productCodes
        * sourceDestCheck
        * groupSet
        * ebsOptimized
        * sriovNetSupport
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    attribute_list = ['instanceType', 'kernel', 'ramdisk', 'userData', 'disableApiTermination',
                      'instanceInitiatedShutdownBehavior', 'rootDeviceName', 'blockDeviceMapping', 'productCodes',
                      'sourceDestCheck', 'groupSet', 'ebsOptimized', 'sriovNetSupport']
    if not any((instance_name, instance_id)):
        raise SaltInvocationError('At least one of the following must be specified: instance_name or instance_id.')
    if instance_name and instance_id:
        raise SaltInvocationError('Both instance_name and instance_id can not be specified in the same command.')
    if attribute not in attribute_list:
        raise SaltInvocationError('Attribute must be one of: {0}.'.format(attribute_list))
    try:
        if instance_name:
            instances = find_instances(name=instance_name, region=region, key=key, keyid=keyid, profile=profile)
            if len(instances) != 1:
                raise CommandExecutionError('Found more than one EC2 instance matching the criteria.')
            instance_id = instances[0]
        attribute = conn.modify_instance_attribute(instance_id, attribute, attribute_value)
        if not attribute:
            return False
        return attribute
    except boto.exception.BotoServerError as exc:
        log.error(exc)
        return False


def get_network_interface_id(name, region=None, key=None, keyid=None,
                             profile=None):
    '''
    Get an Elastic Network Interface id from its name tag.

    .. versionadded:: Boron

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.get_network_interface_id name=my_eni
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
    r = {}
    try:
        enis = conn.get_all_network_interfaces(filters={'tag:Name': name})
        if not enis:
            r['error'] = {'message': 'No ENIs found.'}
        elif len(enis) > 1:
            r['error'] = {'message': 'Name specified is tagged on multiple ENIs.'}
        else:
            eni = enis[0]
            r['result'] = eni.id
    except boto.exception.EC2ResponseError as e:
        r['error'] = __utils__['boto.get_error'](e)
    return r


def get_network_interface(name=None, network_interface_id=None, region=None,
                          key=None, keyid=None, profile=None):
    '''
    Get an Elastic Network Interface.

    .. versionadded:: Boron

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.get_network_interface name=my_eni
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
    r = {}
    result = _get_network_interface(conn, name, network_interface_id)
    if 'error' in result:
        if result['error']['message'] == 'No ENIs found.':
            r['result'] = None
            return r
        return result
    eni = result['result']
    r['result'] = _describe_network_interface(eni)
    return r


def _get_network_interface(conn, name=None, network_interface_id=None):
    r = {}
    if not (name or network_interface_id):
        raise SaltInvocationError(
            'Either name or network_interface_id must be provided.'
        )
    try:
        if network_interface_id:
            enis = conn.get_all_network_interfaces([network_interface_id])
        else:
            enis = conn.get_all_network_interfaces(filters={'tag:Name': name})

        if not enis:
            r['error'] = {'message': 'No ENIs found.'}
        elif len(enis) > 1:
            r['error'] = {'message': 'Name specified is tagged on multiple ENIs.'}
        else:
            eni = enis[0]
            r['result'] = eni
    except boto.exception.EC2ResponseError as e:
        r['error'] = __utils__['boto.get_error'](e)
    return r


def _describe_network_interface(eni):
    r = {}
    for attr in ['status', 'description', 'availability_zone', 'requesterId',
                 'requester_managed', 'mac_address', 'private_ip_address',
                 'vpc_id', 'id', 'source_dest_check', 'owner_id', 'tags',
                 'subnet_id', 'associationId', 'publicDnsName', 'owner_id',
                 'ipOwnerId', 'publicIp', 'allocationId']:
        if hasattr(eni, attr):
            r[attr] = getattr(eni, attr)
    r['region'] = eni.region.name
    r['groups'] = []
    for group in eni.groups:
        r['groups'].append({'name': group.name, 'id': group.id})
    r['private_ip_addresses'] = []
    for address in eni.private_ip_addresses:
        r['private_ip_addresses'].append(
            {'private_ip_address': address.private_ip_address,
             'primary': address.primary}
        )
    r['attachment'] = {}
    for attr in ['status', 'attach_time', 'device_index',
                 'delete_on_termination', 'instance_id',
                 'instance_owner_id', 'id']:
        if hasattr(eni.attachment, attr):
            r['attachment'][attr] = getattr(eni.attachment, attr)
    return r


def create_network_interface(name, subnet_id=None, subnet_name=None,
                             private_ip_address=None, description=None,
                             groups=None, region=None, key=None, keyid=None,
                             profile=None):
    '''
    Create an Elastic Network Interface.

    .. versionadded:: Boron

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.create_network_interface my_eni subnet-12345 description=my_eni groups=['my_group']
    '''
    if not exactly_one((subnet_id, subnet_name)):
        raise SaltInvocationError('One (but not both) of subnet_id or '
                                  'subnet_name must be provided.')

    if subnet_name:
        resource = __salt__['boto_vpc.get_resource_id']('subnet', subnet_name,
                                                        region=region, key=key,
                                                        keyid=keyid,
                                                        profile=profile)
        if 'id' not in resource:
            log.warning('Couldn\'t resolve subnet name {0}.').format(
                subnet_name)
            return False
        subnet_id = resource['id']

    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
    r = {}
    result = _get_network_interface(conn, name)
    if 'result' in result:
        r['error'] = {'message': 'An ENI with this Name tag already exists.'}
        return r
    vpc_id = __salt__['boto_vpc.get_subnet_association'](
        [subnet_id], region=region, key=key, keyid=keyid, profile=profile
    )
    vpc_id = vpc_id.get('vpc_id')
    if not vpc_id:
        msg = 'subnet_id {0} does not map to a valid vpc id.'.format(subnet_id)
        r['error'] = {'message': msg}
        return r
    _groups = __salt__['boto_secgroup.convert_to_group_ids'](
        groups, vpc_id=vpc_id, region=region, key=key,
        keyid=keyid, profile=profile
    )
    try:
        eni = conn.create_network_interface(
            subnet_id,
            private_ip_address=private_ip_address,
            description=description,
            groups=_groups
        )
        eni.add_tag('Name', name)
    except boto.exception.EC2ResponseError as e:
        r['error'] = __utils__['boto.get_error'](e)
        return r
    r['result'] = _describe_network_interface(eni)
    return r


def delete_network_interface(
        name=None, network_interface_id=None, region=None, key=None,
        keyid=None, profile=None):
    '''
    Create an Elastic Network Interface.

    .. versionadded:: Boron

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.create_network_interface my_eni subnet-12345 description=my_eni groups=['my_group']
    '''
    if not (name or network_interface_id):
        raise SaltInvocationError(
            'Either name or network_interface_id must be provided.'
        )
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
    r = {}
    result = _get_network_interface(conn, name, network_interface_id)
    if 'error' in result:
        return result
    eni = result['result']
    try:
        info = _describe_network_interface(eni)
        network_interface_id = info['id']
    except KeyError:
        r['error'] = {'message': 'ID not found for this network interface.'}
        return r
    try:
        r['result'] = conn.delete_network_interface(network_interface_id)
    except boto.exception.EC2ResponseError as e:
        r['error'] = __utils__['boto.get_error'](e)
    return r


def attach_network_interface(device_index, name=None, network_interface_id=None,
                             instance_name=None, instance_id=None,
                             region=None, key=None, keyid=None, profile=None):
    '''
    Attach an Elastic Network Interface.

    .. versionadded:: Boron

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.attach_network_interface my_eni instance_name=salt-master device_index=0
    '''
    if not salt.utils.exactly_one((name, network_interface_id)):
        raise SaltInvocationError(
            "Exactly one (but not both) of 'name' or 'network_interface_id' "
            "must be provided."
        )

    if not salt.utils.exactly_one((instance_name, instance_id)):
        raise SaltInvocationError(
            "Exactly one (but not both) of 'instance_name' or 'instance_id' "
            "must be provided."
        )

    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
    r = {}
    result = _get_network_interface(conn, name, network_interface_id)
    if 'error' in result:
        return result
    eni = result['result']
    try:
        info = _describe_network_interface(eni)
        network_interface_id = info['id']
    except KeyError:
        r['error'] = {'message': 'ID not found for this network interface.'}
        return r

    if instance_name:
        try:
            instance_id = get_id(name=instance_name, region=region, key=key,
                                 keyid=keyid, profile=profile)
        except boto.exception.BotoServerError as e:
            log.error(e)
            return False

    try:
        r['result'] = conn.attach_network_interface(
            network_interface_id, instance_id, device_index
        )
    except boto.exception.EC2ResponseError as e:
        r['error'] = __utils__['boto.get_error'](e)
    return r


def detach_network_interface(
        name=None, network_interface_id=None, attachment_id=None,
        force=False, region=None, key=None, keyid=None, profile=None):
    '''
    Detach an Elastic Network Interface.

    .. versionadded:: Boron

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.detach_network_interface my_eni
    '''
    if not (name or network_interface_id or attachment_id):
        raise SaltInvocationError(
            'Either name or network_interface_id or attachment_id must be'
            ' provided.'
        )
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
    r = {}
    if not attachment_id:
        result = _get_network_interface(conn, name, network_interface_id)
        if 'error' in result:
            return result
        eni = result['result']
        info = _describe_network_interface(eni)
        try:
            attachment_id = info['attachment']['id']
        except KeyError:
            r['error'] = {'message': 'Attachment id not found for this ENI.'}
            return r
    try:
        r['result'] = conn.detach_network_interface(attachment_id, force)
    except boto.exception.EC2ResponseError as e:
        r['error'] = __utils__['boto.get_error'](e)
    return r


def modify_network_interface_attribute(
        name=None, network_interface_id=None, attr=None,
        value=None, region=None, key=None, keyid=None, profile=None):
    '''
    Modify an attribute of an Elastic Network Interface.

    .. versionadded:: Boron

    CLI Example:

    .. code-block:: bash

        salt myminion boto_ec2.modify_network_interface_attribute my_eni attr=description value='example description'
    '''
    if not (name or network_interface_id):
        raise SaltInvocationError(
            'Either name or network_interface_id must be provided.'
        )
    if attr is None and value is None:
        raise SaltInvocationError(
            'attr and value must be provided.'
        )
    r = {}
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
    result = _get_network_interface(conn, name, network_interface_id)
    if 'error' in result:
        return result
    eni = result['result']
    info = _describe_network_interface(eni)
    network_interface_id = info['id']
    # munge attr into what the API requires
    if attr == 'groups':
        _attr = 'groupSet'
    elif attr == 'source_dest_check':
        _attr = 'sourceDestCheck'
    elif attr == 'delete_on_termination':
        _attr = 'deleteOnTermination'
    else:
        _attr = attr
    _value = value
    if info.get('vpc_id') and _attr == 'groupSet':
        _value = __salt__['boto_secgroup.convert_to_group_ids'](
            value, vpc_id=info.get('vpc_id'), region=region, key=key,
            keyid=keyid, profile=profile
        )
        if not _value:
            r['error'] = {
                'message': ('Security groups do not map to valid security'
                            ' group ids')
            }
            return r
    _attachment_id = None
    if _attr == 'deleteOnTermination':
        try:
            _attachment_id = info['attachment']['id']
        except KeyError:
            r['error'] = {
                'message': ('No attachment id found for this ENI. The ENI must'
                            ' be attached before delete_on_termination can be'
                            ' modified')
            }
            return r
    try:
        r['result'] = conn.modify_network_interface_attribute(
            network_interface_id, _attr, _value, attachment_id=_attachment_id
        )
    except boto.exception.EC2ResponseError as e:
        r['error'] = __utils__['boto.get_error'](e)
    return r
