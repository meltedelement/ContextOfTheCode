# Import threading for background processing, queue for thread-safe data storage, and time for delays
import threading
import queue
import time
import logging
#import some of them collectors
from collectors.LocalCollector import LocalDataCollector

#The upload queue class handles the adding of the data to a queue and uploading in background
class UploadQueue:
    def __init__(self, upload_function, maxsize=100):
        #Create a tread-safe queue with a maximum size
        self.queue = queue.Queue(maxsize=maxsize)
        #Store the function that hanles the upload
        self.upload_function = upload_function
        # Set up logging for failures
        logging.basicConfig(filename='uploadqueue.log', level=logging.ERROR,
                            format='%(asctime)s %(levelname)s:%(message)s')
        #Start a background thread to process the queue
        self.worker = threading.Thread(target=self._process_queue, daemon=True)
        self.worker.start()

    def add_to_queue(self, data):
        #Add the items to the queue for uploading
        self.queue.put(data)

    def _process_queue(self):
        #Do the processing of the queue items continuously
        while True:
             #Wait for a data item
            data = self.queue.get()
            try:
                #Call the upload function with the data
                self.upload_function(data)
            except Exception as e:
                #Print if its failed
                print(f"Upload failed: {e}")
                #logs when failed
                logging.error(f"Upload failed for data: {data} | Error: {e}")  # Log the error to a file
                # Optionally, re-queue 
            finally:
                self.queue.task_done()
            time.sleep(0.1)  # Throttle uploads if needed

def upload_function(data):
    print("Uploading:", data)

#Create collector and upload queue
collector = LocalDataCollector(device_id="local-system-001")
upload_queue = UploadQueue(upload_function)

#Collect data and add to queue
message = collector.generate_message()
upload_queue.add_to_queue(message.model_dump())

#wait for all uploads to finish
upload_queue.queue.join()
