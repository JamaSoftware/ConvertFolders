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

# global variables these reset after each set root item is processed
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


def init_logging():
    # Get current date and time for the log file name
    timestamp = datetime.datetime.now()
    # Lets make the datetime pretty
    pretty_timestamp = timestamp.strftime('%Y-%m-%d_%H-%M-%S')
    # Setup log file name
    logfile = 'conversion-logs__' + pretty_timestamp + '.log'
    logging.basicConfig(filename=logfile, level=logging.INFO)


def log(message, is_error):
    print(message)
    if is_error:
        logging.error(message)
    else:
        logging.info(message)

def validate_parameters():
    set_ids_string = config['PARAMETERS']['set item ids']
    folder_api_field_name = config['PARAMETERS']['folder api field name']
    folder_field_value = config['PARAMETERS']['folder field value']
    text_api_field_name = config['PARAMETERS']['text api field name']
    text_field_value = config['PARAMETERS']['text field value']

    if set_ids_string is None or set_ids_string == '':
        log("A value for the 'set item ids' parameter in config file must be provided", True)
        return False
    if folder_api_field_name is None or folder_api_field_name == '':
        log("A value for the 'folder api field name' parameter in config file must be provided", True)
        return False
    if folder_field_value is None or folder_field_value == '':
        log("A value for the 'folder field value' parameter in config file must be provided", True)
        return False
    if text_api_field_name is None or text_api_field_name == '':
        log("A value for the 'text api field name' parameter in config file must be provided", True)
        return False
    if text_field_value is None or text_field_value == '':
        log("A value for the 'text field value' parameter in config file must be provided", True)
        return False

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


def get_create_snapshot():
    create_snapshot = config['OPTIONS']['create snapshot'].lower()
    if create_snapshot == 'false' or create_snapshot == 'no':
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


def validate_config():
    # both credentials and parameters are required
    credentials = ['instance url', 'using oauth', 'username', 'password']
    parameters = ['set item ids', 'folder api field name', 'folder field value']
    # these are optional
    options = ['preserve order', 'stats for nerds', 'create snapshot']

    # lets run some quick validations here
    for credential in credentials:
        if credential not in config['CREDENTIALS']:
            log("Config missing required credential '" + credential
                  + "', confirm this is present in the config.ini file.", True)
            return False
    for parameter in parameters:
        if parameter not in config['PARAMETERS']:
            log("Config missing required parameter '" + parameter
                  + "', confirm this is present in the config.ini file.", True)
            return False

    return True


# lets validate the user credentials
def validate_user_credentials(client):
    response = client.get_server_response()
    status_code = response.status_code
    if status_code != 200:
        return False
    # if we have made it this far then were good
    return True


# this script will only work if the root set its are actually of type set
def validate_set_item_ids(item_ids):
    for item_id in item_ids:
        current_item = client.get_item(item_id)
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
    item_types = client.get_item_types()
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

    api_field_name = str(config['PARAMETERS'][type_string + ' api field name'])
    field_value = str(config['PARAMETERS'][type_string + ' field value'])

    # determine what key were working with here. custom fields will be fieldName $ itemTypeID
    if api_field_name in fields:
        key = api_field_name
    elif api_field_name + '$' + str(item_type_id) in fields:
        key = api_field_name + '$' + str(item_type_id)
    else:
        return False

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

                # dive deeper, grab the picklist option here.
                pick_list_option = get_pick_list_option(value)
                return field_value == pick_list_option.get("name")
            # else lets just assume this is a string were matching up.
            else:
                return field_value == value


def get_pick_list_option(pick_list_option_id):
    # let make sure to only do this work once.
    if pick_list_option_id in pick_list_option_map:
        return pick_list_option_map.get(pick_list_option_id)
    else:
        pick_list_option = client.get_pick_list_option(pick_list_option_id)
        pick_list_option_map[pick_list_option_id] = pick_list_option
        return pick_list_option


def update_resync_list(old_id, new_id):
    global synced_items_list
    updated_synced_item_list = []
    for synced_items in synced_items_list:

        # the synced item list is a list of tuples. which are not mutable
        # first entry
        if synced_items[0] == old_id:
            updated_synced_item_list.append((new_id, synced_items[1]))
        elif synced_items[1] == old_id:
            updated_synced_item_list.append((synced_items[0], new_id))
        else:
            updated_synced_item_list.append(synced_items)

    synced_items_list = updated_synced_item_list


def resync_items(bar):
    for synced_items in synced_items_list:
        try:
            client.post_synced_item(synced_items[0], synced_items[1])
        except APIException as e:
            log('unable to sync item ID:[' + synced_items[0] + '] to item ID:[' + synced_items[1] + ']\n' 
                  'This is likely due to the item types not matching. Make sure need to include all the sets \n' +
                  'that are using reuse and sync.', True)

        bar.next()


def process_synced_items(item_id):
    # do we care about synced items?
    if get_resync_items():
        # lets check to see if there are any synced items on this.
        synced_items = client.get_synced_items(item_id)
        if synced_items is not None and len(synced_items) > 0:
            # save these connections, because we are going to re-establish
            # these later in the script execution.
            for synced_item in synced_items:
                synced_item_id = synced_item.get('id')
                in_list_one = (item_id, synced_item_id) in synced_items_list
                in_list_two = (synced_item_id, item_id) in synced_items_list
                if not in_list_one and not in_list_two:
                    synced_items_list.append((item_id, synced_item_id))


def process_children_items(root_item_id, temp_folder_id, child_item_type, bar):
    # children_items = client.get_children_items(root_item_id)
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
                process_synced_items(item_id)
                folder_id = convert_item_to_folder(child_item, child_item_type, root_item_id)
                item_id_to_child_map[folder_id] = item_id_to_child_map.get(item_id)
                update_resync_list(item_id, folder_id)
                item_id = folder_id
                folder_conversion_count += 1
            elif is_text_conversion_item(fields, item_type_id):
                process_synced_items(item_id)
                text_id = convert_item_to_text(child_item, root_item_id)
                item_id_to_child_map[text_id] = item_id_to_child_map.get(item_id)
                update_resync_list(item_id, text_id)
                text_conversion_count += 1
            # no? well we still need to do work here to maintain order
            else:
                #  unless we don't care about order?
                if get_preserve_order():
                    move_item_to_parent_location(item_id, temp_folder_id)
                    move_item_to_parent_location(item_id, root_item_id)
                    moved_item_count += 1

        # lets check for sub children here and recursively call this if there are
        process_children_items(item_id, temp_folder_id, child_item_type, bar)
        bar.next()


# this is the "convert" (those are dramatic air quotes) here is how we are going to convert this:
#   1. create a folder item with the same parent
#   2. if there are children then move those over to the new folder item too.
#   3. delete the original item
def convert_item_to_folder(item, child_item_type, parent_item_type_id):
    item_id = item.get("id")
    log('Detected item ID:[' + str(item_id) + '] converting this item to a FOLDER...', False)
    folder_id = create_folder(item, child_item_type, parent_item_type_id)
    if folder_id > 0:
        log('Successfully converted item to type text', False)
    children = client.get_children_items(item_id)
    # we will need to iterate over all the children here, and move them to the new folder
    for child in children:
        child_item_id = child.get("id")
        move_item_to_parent_location(child_item_id, folder_id)
    # there should be zero children in the original item now.
    client.delete_item(item_id)
    return folder_id


# this is the "convert" (those are dramatic air quotes) here is how we are going to convert this:
#   1. create a text item with the same parent
#   2. if there are children then move those over to the new folder item too.
#   3. delete the original item
def convert_item_to_text(item, parent_item_type_id):
    item_id = item.get("id")
    log('Detected item ID:[' + str(item_id) + '] converting this item to a TEXT...', False)
    text_id = create_text(item, parent_item_type_id)
    if text_id > 0:
        log('Successfully converted item to type text', False)
    text_item_type_id = text_item_type.get('id')
    children = client.get_children_items(item_id)
    # we will need to iterate over all the children here, and move them to the new folder
    for child in children:
        child_item_type_id = child.get('itemType')
        if child_item_type_id is text_item_type_id:
            child_item_id = child.get("id")
            move_item_to_parent_location(child_item_id, text_id)
        else:
            log('unable to move item ID:[' + str(child_item_id) + '] because this item is NOT of type text.', True)

    # there should be zero children in the original item now.
    client.delete_item(item_id)
    return text_id


# recursively gets all the items and assigns them to a map, also gets the count
def retrieve_items(root_item_id):
    global item_count
    global items_list
    children = client.get_children_items(root_item_id)
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
def create_folder(item, child_item_type, parent_item_id):
    fields = item.get('fields')
    fields = get_fields_payload(fields)
    project = item.get('project')
    folder_item_type_id = folder_item_type.get('id')
    location = {'item': parent_item_id}
    try:
        response = client.post_item(project, folder_item_type_id, child_item_type, location, fields)
    except APIException as e:
        log('Failed to convert item to folder. Exception: ' + str(e) + '\n'
            'item:' + str(item) + '\n' +
            'parent item ID:' + str(parent_item_id), True)
        return -1
    return response


# create a text item
def create_text(item, parent_item_id):
    fields = item.get('fields')
    fields = get_fields_payload(fields)
    project = item.get('project')
    text_item_type_id = text_item_type.get('id')
    location = {'item': parent_item_id}
    try:
        response = client.post_item(project, text_item_type_id, text_item_type_id, location, fields)
    except APIException as e:
        log('Failed to convert item to text. Exception: ' + str(e) + '\n'
            'item:' + str(item) + '\n' +
            'parent item ID:' + str(parent_item_id), True)
        return -1
    return response


# create a temp folder soo we can re-order the items. (API does not allow you to change the order)
def create_temp_folder(root_set_item_id, child_item_type_id):
    item = client.get_item(root_set_item_id)
    project = item.get('project')
    folder_item_type_id = folder_item_type.get('id')
    location = {'item': set_item_id}
    fields = {"name": "TEMP"}
    response = client.post_item(project, folder_item_type_id, child_item_type_id, location, fields)
    return response


def move_item_to_parent_location(item_id, destination_parent_id):
    if item_id == destination_parent_id:
        return
    payload = [
        {
            "op": "replace",
            "path": "/location/parent",
            "value": destination_parent_id
        }
    ]
    client.patch_item(item_id, payload)


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
    start = time.time()
    init_globals()
    init_logging()
    log('\n'
          + '     ____     __   __          _____                      __           \n'
          + '    / __/__  / /__/ /__ ____  / ___/__  ___ _  _____ ____/ /____  ____ \n'
          + '   / _// _ \/ / _  / -_) __/ / /__/ _ \/ _ \ |/ / -_) __/ __/ _ \/ __/ \n'
          + '  /_/  \___/_/\_,_/\__/_/    \___/\___/_//_/___/\__/_/  \__/\___/_/    \n'
          + '                               Jama Software - Professional Services   \n', False)

    config = configparser.ConfigParser()
    config.read('config.ini')

    # read in the configuration, will abort script if missing requried params
    if not validate_config():
        sys.exit()

    client = init_jama_client()

    # validate user data
    if not validate_user_credentials(client):
        log('Invalid username and/or password, please check your credentials and try again.', True)
        sys.exit()
    else:
        log('Connected to <' + config['CREDENTIALS']['instance url'] + '>', False)

    # validate all the parameters for this script
    set_item_ids = get_set_ids()

    if not validate_parameters():
        sys.exit()

    if not get_convert_folders() and not get_convert_texts():
        log('Both convert folders and texts set to false. no work needed, aborting...', True)
        sys.exit()

    # pull down all the meta data for this instance
    log('Retrieving Instance meta data...', False)
    get_meta_data()
    log('Successfully retrieved ' + str(len(item_type_map)) + ' item type definitions.', False)

    # lets validate the user specified set item ids. this script will only work with sets
    if not validate_set_item_ids(set_item_ids):
        log('Invalid set id(s), please confirm that these ids are valid and of type set.', True)
        sys.exit()
    else:
        log('Specified Set IDs ' + str(set_item_ids) + ' are valid', False)

    log(str(set_item_ids) + ' sets being processed, each set will be processed sequentially. \n', False)
    # loop through the list of set item ids
    for set_item_id in set_item_ids:
        set_item = client.get_item(set_item_id)

        # show some data about how we just did
        log('Processing Set <' + config['CREDENTIALS']['instance url'] + '/perspective.req#/containers/'
              + str(set_item_id)
              + '?projectId='
              + str(set_item.get('project'))
              + '>', False)

        # lets pull the entire hierarchy under this set
        log('Retrieving all children items from set id: [' + str(set_item_id) + '] ...', False)
        retrieve_items(set_item_id)
        log('Successfully retrieved ' + str(item_count) + ' items.', False)

        # create a backup of the data
        if get_create_snapshot():
            log('Saving current state of item in set [' + str(set_item_id) + '] to json file.', False)
            create_snapshot(set_item_id)

        # get the child item type form the root set
        child_item_type = get_child_item_type(set_item_id)
        # create a temp folder
        temp_folder_id = create_temp_folder(set_item_id, child_item_type)

        if item_count > 0:
            with ChargingBar('Processing Items', max=item_count, suffix='%(percent).1f%% - %(eta)ds') as bar:
                process_children_items(set_item_id, temp_folder_id, child_item_type, bar)
                bar.finish()

        client.delete_item(temp_folder_id)
        log('Finished processing set id: [' + str(set_item_id) + ']\n', False)
        reset_set_item_variables()

    # do we care about reuse and sync?
    if get_resync_items() and len(synced_items_list) > 0:
        with ChargingBar('ReSyncing Converted Folders', max=len(synced_items_list), suffix='%(percent).1f%% - %(eta)ds') as bar:
            resync_items(bar)
            bar.finish()

    log('\nScript execution finished', False)

    # here are some fun stats for nerds
    if get_stats_for_nerds():
        elapsed_time = '%.2f' % (time.time() - start)
        log('total execution time: ' + elapsed_time + ' seconds', False)
        log('# items converted into folder(s): ' + str(folder_conversion_count), False)
        log('# items converted into text(s): ' + str(text_conversion_count), False)
        log('# items re-indexed: ' + str(moved_item_count), False)
