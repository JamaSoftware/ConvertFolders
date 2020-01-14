# Folder Text Converter
Script that interacts with Jama's API to "convert" items into folders and texts. 

### Script Dependencies
- python 3
- pip
- pipenv (optional)

### Setup Instructions
1. clone this repo
2. navigate to the directory in your terminal
3. setup virtual environment `pipenv --python 3.7`
4. shell in to the enviornment with `pipenv shell`
5. install py-jama-rest-client `pip install py-jama-rest-client`
5. install dependencies `pip install requests` followed by `pip install progress`
6. open up the `config.ini` file to adjust the config variables. there are comments provided in this file. 
7. run the script `python convert_folders.py` (edited) 

### Recommendations
Before running this script it is highly recommended that you create a baseline of all the set items
that are being procressed before running this script. The API does not technically allow for items to be
converted into folders, instead it will create new item and move over all its children items.
Also the API does not allow to reorder an item under the same parent, because of this all items must be moved
into a temp location and then moved back under it's original parent item. Because of these two limitations this 
script can take a very long time to process a large set of items. 

### Synced Items
In order for this script to work with synced items, you will need to include all the synced items within the same run.
Once all the items are converted and re-indexed it then will re-establish the synced items. Its done 
this way because items cannot be synced of different item types, so all the items need to be converted 
first then the syncs be made.
