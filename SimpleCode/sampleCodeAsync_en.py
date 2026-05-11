import time
import requests  # Import the requests library
from datetime import datetime
from com.rfid.helper import *
from com.rfid.enumeration import *
from com.rfid.Reader import *
from com.rfid.models import *
from com.rfid.interface import *

class SampleCodeNew(IAsynchronousMessage):
    def __init__(self):
        self.processed_tags = set()  # Initialize a set to keep track of processed tags

    def OutputTags(self, tag):
        try:
            tag_epc = tag._EPC
            if tag_epc not in self.processed_tags:
                print("EPC: " + tag_epc +" datetime:  "+ str(datetime.now()))
                self.processed_tags.add(tag_epc)  # Add tag to the set

                # Send the tag to the URL
                url = f"http://192.168.20.244/QuickToll/quick_tag.php?tag={tag_epc}"
                response = requests.get(url)

                # Check the response from the server
                if response.status_code == 200:
                    print(f"Tag {tag_epc} sent successfully")
                else:
                    print(f"Failed to send tag {tag_epc}. Status code: {response.status_code}")

            else:
                print("Tag already processed, ignoring: " + tag_epc + " datetime: " + str(datetime.now()))
        except Exception as e:
            print("Method OutputTags failed with error message: %s" % e)

    def OutputTagsOver(self, connID):
        print('This connection ' + connID + ' is over for reading tags')

    def main(self):
        log = SampleCodeNew()
        reader = Reader()
        if reader.initReader("TCP:192.168.20.246:9090", log):
            print("Connection created successfully!")
            # Set the working antenna. If not, antenna 1 will be used by default.
            readerAntPlan = ReaderWorkingAntSet_Model([1])
            #print('Setting up the working antenna result:')
            #print(reader.paramSet(EReaderEnum.WO_RFIDWorkingAnt, readerAntPlan))
            # Get reader SN
            readerInfo = ReaderInfo_Model()
            readerResult = reader.paramGet(EReaderEnum.RO_ReaderInformation, readerInfo)
            if readerResult == EReaderResult.RT_OK:
                print('Reader SN is: ')
                print(readerInfo.readerSN)
            #   Set Extended Read TID
            # readTID = ReadExtendedArea_Model(EReadBank.TID, 0, 6, "")
            # readExtendedAreaList = []
            # readExtendedAreaList.append(readTID)
            # print('Set Extended Read Result:')
            # print(reader.paramSet(EReaderEnum.WO_RFIDReadExtended, readExtendedAreaList))
            print('Start tag reading result:')
            print(reader.inventory(),datetime.now())
            time.sleep(60)
            #reader.stop()
            #reader.closeConnect()
        else:
            print("Failed to create connection!")

if __name__ == '__main__':
    s = SampleCodeNew()
    s.main()

# print(Reader.getDetailError(EReaderResult.RT_OK))
