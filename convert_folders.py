import os
import sys
import json
import datetime
import time as time
import configparser
import logging
from progress.bar import ChargingBar
from py_jama_rest_client.client import JamaClient, APIException

# make the client and config globally available
global config
global client

# global variables these reset after each set root item is processed this is redundant
global folder_item_type
global text_item_type
global set_item_type
global item_type_map
global item_id_to_child_map
global item_id_to_item_map
global pick_list_option_map
global item_count
global items_list

# dont reset this list. we will need it as a post process to
# re-sync all the converted items.
global synced_items_list
synced_items_list = []

# stats for nerds (don't reset these values)
global folder_conversion_count
global text_conversion_count
global moved_item_count
folder_conversion_count = 0
text_conversion_count = 0
moved_item_count = 0

# variable
MAX_RETRIES = 3


def init_globals():
    global folder_item_type
    global text_item_type
    global set_item_type
    global item_type_map
    global item_id_to_child_map
    global item_id_to_item_map
    global pick_list_option_map
    global item_count
    global items_list
    global synced_items_list
    folder_item_type = None
    text_item_type = None
    set_item_type = None
    item_type_map = {}
    item_id_to_child_map = {}
    item_id_to_item_map = {}
    pick_list_option_map = {}
    item_count = 0
    items_list = []


def reset_set_item_variables():
    global item_id_to_child_map
    global item_id_to_item_map
    global item_count
    global items_list
    global synced_items_list
    item_id_to_child_map = {}
    item_id_to_item_map = {}
    item_count = 0
    items_list = []


def init_jama_client():
    instance_url = str(config['CREDENTIALS']['instance url'])
    using_oauth = config['CREDENTIALS']['using oauth'] == 'True'
    username = str(config['CREDENTIALS']['username'])
    password = str(config['CREDENTIALS']['password'])
    return JamaClient(instance_url, credentials=(username, password), oauth=using_oauth)


def init_logger():
    # Setup logging
    try:
        os.makedirs('logs')
    except FileExistsError:
        pass

    current_date_time = datetime.datetime.now().strftime('%m-%d-%Y_%H-%M-%S')
    log_file = 'logs/' + str(current_date_time) + '.log'

    logging.basicConfig(filename=log_file, level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        datefmt='%H:%M:%S')

    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler(sys.stdout))
    return logger


def validate_parameters():
    set_ids_string = config['PARAMETERS']['set item ids']
    folder_api_field_names = config['PARAMETERS']['folder api field names']
    folder_field_values = config['PARAMETERS']['folder field values']
    text_api_field_names = config['PARAMETERS']['text api field names']
    text_field_values = config['PARAMETERS']['text field values']

    # we need at least one set ot process here
    if set_ids_string is None or set_ids_string == '':
        logger.error("A value for the 'set item ids' parameter in config file must be provided")
        return False

    #  we converting items into folders? we are going to need the these params.
    if get_convert_folders():
        if folder_api_field_names is None or folder_api_field_names == '':
            logger.error("A value for the 'folder api field names' parameter in config file must be provided")
            return False
        if folder_field_values is None or folder_field_values == '':
            logger.error("A value for the 'folder field values' parameter in config file must be provided")
            return False
        if len(folder_api_field_names) == len(folder_field_values):
            logger.error("There must be a corresponding 'folder field value' for every 'folder api field name'")

    #  we converting items into texts? we are going to need the these params.
    if get_convert_texts():
        if text_api_field_names is None or text_api_field_names == '':
            logger.error("A value for the 'text api field names' parameter in config file must be provided")
            return False
        if text_field_values is None or text_field_values == '':
            logger.error("A value for the 'text field values' parameter in config file must be provided")
            return False
        if len(text_api_field_names) == len(text_field_values):
            logger.error("There must be a corresponding 'text field value' for every 'text api field name'")

    return True


def get_convert_folders():
    convert_folders = config['PARAMETERS']['convert folders'].lower()
    if convert_folders == 'false' or convert_folders == 'no':
        return False
    else:
        return True


def get_convert_texts():
    convert_texts = config['PARAMETERS']['convert texts'].lower()
    if convert_texts == 'false' or convert_texts == 'no':
        return False
    else:
        return True


def get_resync_items():
    reync_items = config['PARAMETERS']['resync items'].lower()
    if reync_items == 'false' or reync_items == 'no':
        return False
    else:
        return True


def get_preserve_order():
    preserve_order = config['OPTIONS']['preserve order'].lower()
    if preserve_order == 'false' or preserve_order == 'no':
        return False
    else:
        return True


def get_stats_for_nerds():
    stats_for_nerds = config['OPTIONS']['stats for nerds'].lower()
    if stats_for_nerds == 'false' or stats_for_nerds == 'no':
        return False
    else:
        return True


def get_set_ids():
    set_ids_string = config['PARAMETERS']['set item ids']
    split_ids = set_ids_string.split(',')
    return_list = []
    for split_id in split_ids:
        return_list.append(int(split_id.strip()))
    return return_list


def get_conversion_field_names(field_type):
    set_ids_string = config['PARAMETERS'][field_type + ' api field names']
    split_ids = set_ids_string.split(',')
    return_list = []
    for split_id in split_ids:
        return_list.append(split_id.strip())
    return return_list


def get_conversion_field_values(field_type):
    set_ids_string = config['PARAMETERS'][field_type + ' field values']
    split_ids = set_ids_string.split(',')
    return_list = []
    for split_id in split_ids:
        return_list.append(split_id.strip())
    return return_list


def validate_credentials():
    # both credentials and parameters are required
    credentials = ['instance url', 'using oauth', 'username', 'password']
    # these are optional
    options = ['preserve order', 'stats for nerds', 'create snapshot']

    # lets run some quick validations here
    for credential in credentials:
        if credential not in config['CREDENTIALS']:
            logger.error("Config missing required credential '" + credential
                         + "', confirm this is present in the config.ini file.")
            return False
    return True


# lets validate the user credentials
def validate_user_credentials(client):
    try:
        endpoints = client.get_available_endpoints()
    except APIException as e:
        logger.error('Unable to connect to instance... Exception:' + str(e))
        return False
    if endpoints is None or len(endpoints) < 1:
        return False
    # if we have made it this far then were good
    return True


# this script will only work if the root set its are actually of type set
def validate_set_item_ids(item_ids):
    for item_id in item_ids:
        try:
            current_item = client.get_item(item_id)
        except APIException as e:
            logger.error("unable to validate the set item ids. Exception: " + str(e))
            return False
        if current_item.get('itemType') != set_item_type.get('id'):
            return False
    return True


# get at that instance meta data
def get_meta_data():
    global folder_item_type
    global text_item_type
    global set_item_type
    global item_type_map
    global pick_list_option_map

    # lets collect all the instance meta data were going to need before we run the conversions
    try:
        item_types = client.get_item_types()
    except APIException as e:
        logger.error('Unable to retrieve item type data. Exception: ' + str(e))
        return False
    for item_type in item_types:
        # grab the type key, this *should* be consistent across Jama connect instances
        type_key = item_type.get('typeKey')
        item_type_id = item_type.get('id')
        if type_key == 'FLD':
            folder_item_type = item_type
        if type_key == 'TXT':
            text_item_type = item_type
        if type_key == 'SET':
            set_item_type = item_type

        item_type_map[item_type_id] = item_type
    return True


def is_folder_conversion_item(fields, item_type_id):
    if get_convert_folders():
        return is_conversion_item(fields, item_type_id, 'folder')
    else:
        return False


def is_text_conversion_item(fields, item_type_id):
    if get_convert_texts():
        return is_conversion_item(fields, item_type_id, 'text')
    else:
        return False


# helper method to determine if this is an item that we are going to convert
def is_conversion_item(fields, item_type_id, type_string):
    # is this already a folder? no work needed here then
    if item_type_id == folder_item_type.get('id'):
        return False

    field_definitions = item_type_map[item_type_id].get('fields')
    # match on the folder api field name
    key = None
    value = None

    field_names = get_conversion_field_names(type_string)
    field_values = get_conversion_field_values(type_string)

    # api_field_name = str(config['PARAMETERS'][type_string + ' api field name'])
    # field_value = str(config['PARAMETERS'][type_string + ' field value'])

    for index in range(len(field_names)):
        field_name = field_names[index]
        field_value = field_values[index]

        # determine what key were working with here. custom fields will be fieldName $ itemTypeID
        # for field_name in field_names:
        api_field_name = str(field_name)
        if api_field_name in fields:
            key = api_field_name
        elif api_field_name + '$' + str(item_type_id) in fields:
            key = api_field_name + '$' + str(item_type_id)

        # no key? then give up now.
        if key is None:
            continue

        # grab the field value
        value = fields.get(key)

        # iterate over all the field definitions here to find a match on the field were working with here
        # the point of doing this is to determine the field type. if look up -> do more work.
        for field_definition in field_definitions:
            field_definitions_name = field_definition.get('name')
            # found it!, lets look and see what were working with here.
            if field_definitions_name == key:
                # is this a lookup of type picklist?
                if field_definition.get('fieldType') == 'LOOKUP' and 'pickList' in field_definition:

                    # we have a match on the id?
                    if field_value == value:
                        return True

                    # dive deeper, resolve the lookup id to a value and check that.
                    pick_list_option = get_pick_list_option(value)
                    if field_value == pick_list_option.get("name"):
                        return True
                # else lets just assume this is a string were matching up.
                else:
                    if field_value == value:
                        return True
    return False


def get_pick_list_option(pick_list_option_id):
    # let make sure to only do this work once.
    if pick_list_option_id in pick_list_option_map:
        return pick_list_option_map.get(pick_list_option_id)
    else:
        try:
            pick_list_option = client.get_pick_list_option(pick_list_option_id)
        except APIException as e:
            logger.error('Unable to retrieve picklist options for picklist ID:[' + str(
                pick_list_option_id) + ']. Exception: ' + str(e))
            return None
        pick_list_option_map[pick_list_option_id] = pick_list_option
        return pick_list_option


def process_children_items(root_item_id, child_item_type, bar):
    global moved_item_count, folder_conversion_count, text_conversion_count, synced_items_list
    children_items = item_id_to_child_map.get(root_item_id)

    # lets first do a quick pass to see if we need to process these children items
    conversions_detected = False
    for child_item in children_items:
        if is_folder_conversion_item(child_item.get('fields'), child_item.get('itemType')):
            conversions_detected = True
            break
        if is_text_conversion_item(child_item.get('fields'), child_item.get('itemType')):
            conversions_detected = True
            break

    # process all the children
    for child_item in children_items:
        item_type_id = child_item.get('itemType')
        fields = child_item.get('fields')
        item_id = child_item.get('id')

        # can we skip the work here?
        if conversions_detected:

            # we got a match on the value? lets "convert" it
            if is_folder_conversion_item(fields, item_type_id):
                folder_id = convert_item_to_folder(child_item, child_item_type, root_item_id)
                if folder_id == -1:
                    continue
                item_id_to_child_map[folder_id] = item_id_to_child_map.get(item_id)
                item_id = folder_id
                folder_conversion_count += 1
            elif is_text_conversion_item(fields, item_type_id):
                text_id = convert_item_to_text(child_item, root_item_id)
                if text_id == -1:
                    continue
                item_id_to_child_map[text_id] = item_id_to_child_map.get(item_id)
                text_conversion_count += 1

        # lets check for sub children here and recursively call this if there are
        process_children_items(item_id, child_item_type, bar)
        bar.next()


def validate_item_id(item_id):
    try:
        client.get_item(item_id)
        # if we can pull this down via the api then we good.
        return True
    except APIException as e:
        # else invalid
        return False


# this is the "convert" (those are dramatic air quotes) here is how we are going to convert this:
#   1. create a folder item with the same parent
#   2. if there are children then move those over to the new folder item too.
#   3. delete the original item
def convert_item_to_folder(item, child_item_type, parent_item_type_id):
    item_id = item.get("id")
    sort_order = item["location"]["sortOrder"]
    # lets confirm this item id is valid before we continue.
    if not validate_item_id(item_id):
        return -1

    logger.info('Detected item ID:[' + str(item_id) + '] converting this item to a FOLDER...')
    folder_id = create_folder(item, child_item_type, parent_item_type_id, sort_order)
    if folder_id > 0:
        logger.info('Successfully created item of type folder with new ID:[' + str(folder_id) + ']')
    else:
        logger.error('Failed to convert item ID:[' + str(item_id) + '] to FOLDER')
        return -1

    move_children(item_id, folder_id)

    if not safe_delete(item_id):
        logger.error('Failed to delete original item ID:[' + str(item_id) + ']. this will be an extra item')
    else:
        logger.info('Successfully converted item from id:[' + str(item_id) + '] --> into id:[' + str(folder_id) + ']')

    return folder_id


def move_children(parent_id, destination_id):
    children = []
    try:
        children = client.get_item_children(parent_id)
    # this is likely caused from a bad resource id (item id)
    except APIException as e:
        logger.error('Unable to get retrieve children for item ID:[' + str(parent_id) + ']... ' + str(e))
    # we will need to iterate over all the children here, and move them to the new folder
    for child in children:
        child_item_id = child.get("id")
        # if we fail then we need to skip processing siblings
        if not move_item_to_parent_location(child_item_id, destination_id, None):
            logger.error('Failed to move item child item ID:[' + str(child_item_id) + '] to parent location ID:[' + str(
                destination_id) + ']')
            break

    # there is a defect with the API move operation where some move ops may fail. the following checks for
    # any remaining lost children and puts them under the correct parent.

    # do we have any remaining children here? lets validate that the move operations were sucessful
    lost_children = client.get_item_children(parent_id)
    if len(lost_children) > 0:
        # iterate over the remaining children here
        for lost_child in lost_children:

            sort_order = 0

            # we are going to need to determine the sort order of this lost child
            for original_child in children:
                if lost_child['id'] == original_child['id']:
                    sort_order = original_child['location']['sortOrder']
                    break

            # lets move this lost child to its proper parent
            lost_child_item_id = lost_child.get("id")
            # if we fail then we need to skip processing siblings
            if not move_item_to_parent_location(lost_child_item_id, destination_id, sort_order):
                logger.error(
                    'Failed to move item child item ID:[' + str(lost_child_item_id) + '] to parent location ID:[' + str(
                        destination_id) + ']')
                break


# this is the "convert" (those are dramatic air quotes) here is how we are going to convert this:
#   1. create a text item with the same parent
#   2. if there are children then move those over to the new folder item too.
#   3. delete the original item
def convert_item_to_text(item, parent_item_type_id):
    item_id = item.get("id")
    sort_order = item["location"]["sortOrder"]
    # lets confirm this item id is valid before we continue.
    if not validate_item_id(item_id):
        return -1

    logger.info('Detected item ID:[' + str(item_id) + '] converting this item to a TEXT...')
    text_id = create_text(item, parent_item_type_id, sort_order)
    if text_id > 0:
        logger.info('Successfully created new item of type text with new ID:[' + str(text_id) + ']')
    else:
        logger.error('Failed to convert item ID:[' + str(item_id) + '] to TEXT')
        return -1

    move_children(item_id, text_id)

    if not safe_delete(item_id):
        logger.error('Failed to delete original item ID:[' + str(item_id) + ']. this will be an extra item')
    else:
        logger.info('Successfully converted item from id:[' + str(item_id) + '] --> into id:[' + str(text_id) + ']')

    return text_id


def safe_delete(item_id):
    # there should be zero children in the original item now.
    if is_safe_for_delete(item_id):
        try:
            response = client.delete_item(item_id)
            if response == 204:
                return True
            else:
                logger.error(
                    'Unable to delete the original item ID:[' + str(item_id) + ']. with status code: ' + str(response))
        except APIException as e:
            logger.error('Unable to delete the original item ID:[' + str(item_id) + ']... ' + str(e))
    else:
        logger.error('Unable to delete the original item ID:[' + str(
            item_id) + ']. This item still has children and is not safe for removal')
    return False


def is_safe_for_delete(item_id):
    try:
        # validate that there is no more children on this item before we claim its safe for delete
        children = client.get_item_children(item_id)
        if children is None or children is [] or len(children) == 0:
            return True
        else:
            return False

    except APIException as e:
        logger.error('Unable to find item with id:[' + str(item_id) + ']')
        return False


# recursively gets all the items and assigns them to a map, also gets the count
def retrieve_items(root_item_id):
    global item_count
    global items_list
    try:
        children = client.get_item_children(root_item_id)
    except APIException as e:
        logger.error('unable to retrieve child items for item ID:[' + str(root_item_id) + ']. Exception: ' + str(e))
        return None
    items_list += children
    item_count += len(children)
    item_id_to_child_map[root_item_id] = children
    # we need to get all the children items too.
    for child in children:
        child_id = child.get('id')
        retrieve_items(child_id)


# the point of this method is to filter out the read only fields its okay to have extra fields
# that dont map, but the read only ones will cause the API to throw errors.
def get_fields_payload(fields):
    #  we have already pulled down all the item type meta data, lets use it here
    global item_type_map
    item_type_definition = folder_item_type
    item_type_fields = item_type_definition.get('fields')

    # we will be sending back a payload all ready for the API to consume
    payload = {}

    # loop through each field from the passed in fields object
    for field_name, field_value in fields.items():
        read_only = True

        # loop through the corresponding item type def fields.
        for item_type_field in item_type_fields:
            # match by the field api name
            if item_type_field.get('name') == field_name:
                read_only = item_type_field.get('readOnly')
                break
        if not read_only:
            payload[field_name] = field_value

    return payload


# create a folder item
def create_folder(item, child_item_type, parent_item_id, sort_order):
    fields = item.get('fields')
    fields = get_fields_payload(fields)
    project = item.get('project')
    folder_item_type_id = folder_item_type.get('id')
    location = {'item': parent_item_id}
    global_id = None
    # we resyncing items?
    if get_resync_items():
        global_id = 'FOLDER-' + item.get('globalId')
    try:
        response = client.post_item(project, folder_item_type_id, child_item_type, location, fields, global_id)
        location_payload = [{
            "op": "replace",
            "path": "/location/sortOrder",
            "value": sort_order
        }]
        client.patch_item(response, location_payload)
    except APIException as e:
        logger.error('Failed to convert item to folder. Exception: ' + str(e) + '\n'
                                                                                'item:' + str(item) + '\n' +
                     'parent item ID:' + str(parent_item_id))
        return -1
    return response


# create a text item
def create_text(item, parent_item_id, sort_order):
    fields = item.get('fields')
    fields = get_fields_payload(fields)
    project = item.get('project')
    text_item_type_id = text_item_type.get('id')
    location = {'item': parent_item_id}
    global_id = None
    # we resyncing items?
    if get_resync_items():
        global_id = 'TEXT-' + item.get('globalId')
    try:
        response = client.post_item(project, text_item_type_id, text_item_type_id, location, fields, global_id)
        location_payload = [{
            "op": "replace",
            "path": "/location/sortOrder",
            "value": sort_order
        }]
        client.patch_item(response, location_payload)
    except APIException as e:
        logger.error('Failed to convert item to text. Exception: ' + str(e) + '\n'
                                                                              'item:' + str(item) + '\n' +
                     'parent item ID:' + str(parent_item_id))
        return -1
    return response


# create a temp folder soo we can re-order the items. (API does not allow you to change the order)
def create_temp_folder(root_set_item_id, child_item_type_id):
    item = client.get_item(root_set_item_id)
    project = item.get('project')
    folder_item_type_id = folder_item_type.get('id')
    location = {'item': set_item_id}
    fields = {"name": "TEMP"}
    try:
        response = client.post_item(project, folder_item_type_id, child_item_type_id, location, fields, None)
    except APIException as e:
        logger.error('Unable to create a temporary folder for reindexing items. Exception e: ' + str(e))
        return None
    return response


def move_item_to_parent_location(item_id, destination_parent_id, sort_order):
    if item_id == destination_parent_id:
        return False

    payload = [{
        "op": "replace",
        "path": "/location/parent",
        "value": destination_parent_id
    }]

    if sort_order is not None:
        payload.append({
            "op": "replace",
            "path": "/location/sortOrder",
            "value": sort_order
        })

    retry_counter = 0
    while retry_counter < MAX_RETRIES:
        try:
            client.patch_item(item_id, payload)
            time.sleep(1)
            if validate_move_operation(item_id, destination_parent_id, sort_order):
                return True
            else:
                # wait a sec before proceeding to try again.
                time.sleep(1)
                move_item_to_parent_location(item_id, destination_parent_id, sort_order)
        except APIException as e:
            logger.error('Unable to move item ID:[' + str(item_id) + '] :: ' + str(e))
            retry_counter += 1
            time.sleep(retry_counter * retry_counter)
    logger.error('Failed all ' + str(MAX_RETRIES) + ' attempts to move item ID:[' + str(item_id) + ']')
    return False


# i suspect we cannot trust the move operation on sort order.
def validate_move_operation(item_id, destination_parent_id, sort_order):
    try:
        item = client.get_item(item_id)
    except APIException as e:
        return False

    if item['location']['parent']['item'] != destination_parent_id:
        return False
    elif sort_order is not None and item['location']['sortOrder'] != sort_order:
        return False
    else:
        return True


def get_child_item_type(item_id):
    item = client.get_item(item_id)
    return item.get("childItemType")


def create_snapshot(set_id):
    ts = time.time()
    time_stamp = datetime.datetime.fromtimestamp(ts).strftime('%d-%m-%Y_%H-%M-%S')
    file_name = 'backup_set_ID-' + str(set_id) + '___' + str(time_stamp) + '.json'
    with open(file_name, 'w') as outfile:
        json.dump(items_list, outfile)


if __name__ == '__main__':
    global config
    global client
    logger = init_logger()
    start = time.time()
    init_globals()
    logger.info('\n'
                + '     ____     __   __          _____                      __           \n'
                + '    / __/__  / /__/ /__ ____  / ___/__  ___ _  _____ ____/ /____  ____ \n'
                + '   / _// _ \/ / _  / -_) __/ / /__/ _ \/ _ \ |/ / -_) __/ __/ _ \/ __/ \n'
                + '  /_/  \___/_/\_,_/\__/_/    \___/\___/_//_/___/\__/_/  \__/\___/_/    \n'
                + '                               Jama Software - Professional Services   \n')

    config = configparser.ConfigParser()
    config.read('config.ini')

    # read in the configuration, will abort script if missing requried params
    if not validate_credentials():
        sys.exit()

    client = init_jama_client()

    # validate user data
    if not validate_user_credentials(client):
        logger.error('Invalid username and/or password, please check your credentials and try again.')
        sys.exit()
    else:
        logger.info('Connected to <' + config['CREDENTIALS']['instance url'] + '>')

    # validate all the parameters for this script
    set_item_ids = get_set_ids()

    if not validate_parameters():
        logger.error('Please verify that your config.ini parameters are correct and try again.')
        sys.exit()

    if not get_convert_folders() and not get_convert_texts():
        logger.info('Both convert folders and texts set to false. no work needed, aborting...')
        sys.exit()

    # pull down all the meta data for this instance
    logger.info('Retrieving Instance meta data...')
    if not get_meta_data():
        logger.error('Unable to retrieve instance meta data')
        sys.exit()
    logger.info('Successfully retrieved ' + str(len(item_type_map)) + ' item type definitions.')

    # lets validate the user specified set item ids. this script will only work with sets
    if not validate_set_item_ids(set_item_ids):
        logger.error('Invalid set ID(s), please confirm that these IDs are valid and of type set.')
        sys.exit()
    else:
        logger.info('Specified Set ID(s) ' + str(set_item_ids) + ' are valid')

    logger.info(str(set_item_ids) + ' sets being processed, each set will be processed sequentially. \n')
    # loop through the list of set item ids
    for set_item_id in set_item_ids:
        try:
            set_item = client.get_item(set_item_id)
        except APIException as e:
            logger.error('Unable to identify set item ID:[' + str(set_item_id) + '] Exception: ' + str(e))
            logger.error('skipping processing this set...')
            continue

        # show some data about how we just did
        logger.info('Processing Set <' + config['CREDENTIALS']['instance url'] + '/perspective.req#/containers/'
                    + str(set_item_id) + '?projectId=' + str(set_item.get('project')) + '>')

        # lets pull the entire hierarchy under this set
        logger.info('Retrieving all children items from set id: [' + str(set_item_id) + '] ...')
        retrieve_items(set_item_id)
        logger.info('Successfully retrieved ' + str(item_count) + ' items.')

        # get the child item type form the root set
        child_item_type = get_child_item_type(set_item_id)

        if item_count > 0:
            with ChargingBar('Processing Items', max=item_count, suffix='%(percent).1f%% - %(eta)ds') as bar:
                process_children_items(set_item_id, child_item_type, bar)
                bar.finish()

        logger.info('Finished processing set id: [' + str(set_item_id) + ']\n')
        reset_set_item_variables()

    logger.info('\nScript execution finished')

    # here are some fun stats for nerds
    if get_stats_for_nerds():
        elapsed_time = '%.2f' % (time.time() - start)
        logger.error('total execution time: ' + str(elapsed_time) + ' seconds')
        logger.error('# items converted into folder(s): ' + str(folder_conversion_count))
        logger.error('# items converted into text(s): ' + str(text_conversion_count))
