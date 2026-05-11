import time 

from com.rfid.Reader import *
from com.rfid.enumeration import *
from com.rfid.interface import *
from com.rfid.models import *

class Text():
    def main(self):
        reader = Reader()
        if reader.initReader("TCP:192.168.21.181:9090"):
            #   Set the working antenna, if not set, the default antenna 1 is used
            readerAntPlan = ReaderWorkingAntSet_Model([1])
            print('Setting up the working antenna result:', reader.paramSet(EReaderEnum.WO_RFIDWorkingAnt, readerAntPlan))
            # Set the buzzer parameter to achieve a tag reading tone
            setReaderBuzzer = ReaderBuzzer_Model()
            setReaderBuzzer.buzzerControl = EBuzzerControl.ReaderControl
            if reader.paramSet(EReaderEnum.RW_ReaderBuzzerSwitch, setReaderBuzzer) == EReaderResult.RT_OK:
                print('Set the reader buzzer tone successfully!\n --------')
            else:
                print('Set the reader buzzer tone failed!')
            #   Start synchronous reading
            readList = []
            reader.read(500, readList)
            for tag in readList:
                print("ReaderName:" + tag._ReaderName + ",EPC:" + tag._EPC + ",TID:" + tag._TID)
            #   Stop reading, close connection
            reader.stop()
            reader.closeConnect()

        else:
            print("Failed to create connection!")
        reader.closeConnect()


if __name__ == '__main__':
    s = Text()
    s.main()