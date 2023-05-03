import importlib.metadata
import argparse
import configparser
import asyncio
import importlib
import os
import signal
import logging
from smadict import SMA_Dict

# Configure logging to print warn-level messages to the console
logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.WARN,
    datefmt='%Y-%m-%d %H:%M:%S')

# Signal to stop gracefully
_do_stop = False

# Create a shared dictionary object to be filled by sources and processed by sinks
sma_dict = SMA_Dict()

# Define the directory containing the data-source plugins
SOURCES_DIR = "plugins/sources"
sources = []

# Define the directory containing the data-sink plugins
SINKS_DIR = "plugins/sinks"
sinks = []

def load_plugins(plugin_dir, plugins):
    '''
    Load plugins from a given directory and append them to a list.

    Args:
        plugin_dir (str): The directory to search for plugins.
        plugins (list): The list to which to append loaded plugins.
    '''
    # Dictionaries to hold the modules and configs we find in the given directory
    modules = {}
    configs = {}

    # Recursively search the directory and its subdirectories for Python files
    for feature in os.listdir(plugin_dir):
        for filename in os.listdir(os.path.join(plugin_dir, feature)):
            # If the file has a .py extension, add it to the dictionary
            if filename.endswith('.py'):
                modules[feature] = os.path.join(plugin_dir, feature, filename)
                logging.debug(f"Found .py file for {feature} plugin")

            # If the file has a .conf extension, store the config for later
            elif filename.endswith('.conf'):
                config = configparser.ConfigParser()        
                config.read(os.path.join(plugin_dir, feature, filename))
                configs[feature] = config
                logging.debug(f"Found .conf file for {feature} plugin")

    # Iterate over the modules and attempt to load each one
    for module_name, module_path in modules.items():
        startlen = len(plugins)
        try:
            # Use the importlib module to load the module
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Get the "execute" function from the module and add it to the plugins list
            if configs.get(module_name):
                plugins.append((getattr(module, "execute"), configs[module_name]))
            else:
                plugins.append((getattr(module, "execute"), {}))
        except ImportError as e:
            logging.error(f"Could not import module {module_name}: {e}")
        except AttributeError:
            logging.warn(f"Script {module_path} does not have the method execute()")

        # If plugins array still contains the same number of entries as above, nothing was added (and so nothing can be executed)
        if len(plugins) == startlen:
            logging.error(f"Module {module_name} does not have any script with method execute()")

def source_runner(function, config, add_data, dostop):
    '''
    Run a source function in a separate thread.

    Args:
        function (function): The source function to run.
        add_data (function): A function to add data to the shared dictionary.
        dostop (function): A function to determine when to stop the thread.
    '''
    function(config, add_data, dostop)

def sink_runner(function, config, get_items, register_callback, do_stop):
    '''
    Run a sink function in a separate thread.

    Args:
        function (function): The sink function to run.
        get_iter (function): An iterator for the shared dictionary.
        dostop (function): A function to determine when to stop the thread.
    '''
    function(config, get_items, register_callback, do_stop)

def signal_handler(sig, frame):
    '''
    Function to handle a signal received by the process.

    Args:
        sig (int): The signal number received.
        frame (object): The current stack frame.

    Returns:
        None
    '''
    logging.info('Exiting...')
    global _do_stop 
    _do_stop = True

def add_item(key, value):
    '''
    Add item to the shared dictionary.

    Args:
        key (str): The key to use for the data.
        value (any): The data to add to the dictionary.
    '''
    sma_dict[key] = value

def get_items():
    '''
    Get iterator for the shared dictionary.
    '''
    return dict(sma_dict)

def register_callback(sink_callback):
    '''
    Add callback function for item-added notifications to shared dictionary.

    Args:
        sink_callback (function): The callback function.
    '''
    sma_dict.register_callback(sink_callback)

def do_stop():
    '''
    Determine when to stop the source threads.

    Returns:
        bool: True if the source threads should stop, False otherwise.
    '''
    return _do_stop

async def main(args):
    '''
    Main function that loads plugins, starts source and sink threads and waits for them to complete.
    '''
   
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        logging.debug('Verbose output enabled')
 
    if args.verboser:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug('Verbose output enabled')

    # Main business logic
    load_plugins(SOURCES_DIR, sources)
    load_plugins(SINKS_DIR, sinks)

    tasks = []
    for function, config in sources:
        tasks.append(asyncio.to_thread(function, config, add_item, do_stop, ))

    for function, config in sinks:
        tasks.append(asyncio.to_thread(function, config, get_items, register_callback, do_stop, ))

    await asyncio.gather(*tasks)
    logging.info('Done')

if __name__ == '__main__':
    # We want to react gracefully to SIGINT
    signal.signal(signal.SIGINT, signal_handler)

    # Prepare cmdline arg parser
    package_name = 'smahub'
    try:
        version = importlib.metadata.version(package_name)
        summary = importlib.metadata.metadata(package_name)['Summary']

    except importlib.metadata.PackageNotFoundError:
        version = 'unknown'
        summary = 'not available'

    # Set up argument parser
    parser = argparse.ArgumentParser(prog=package_name, description=summary)
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('-V', '--verboser', action='store_true', help='Enable even more verbose output')
    parser.add_argument('--version', action='version', version='%(prog)s '+version)

    # Parse command-line arguments
    args = parser.parse_args()

    asyncio.run(main(args))