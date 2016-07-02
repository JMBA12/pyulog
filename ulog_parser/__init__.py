
from __future__ import print_function

import numpy as np
import struct, sys

__author__  = "Beat Kueng"


# check python version
if sys.hexversion >= 0x030000F0:
    runningPython3 = True
    def parseString(cstr):
        return str(cstr, 'ascii')
else:
    runningPython3 = False
    def parseString(cstr):
        return str(cstr)


class ULog:
    """
    This class parses an ulog file
    """

    """ constants """
    HEADER_BYTES = '\x55\x4c\x6f\x67\x01\x12\x35'

    # message types
    MSG_TYPE_FORMAT = ord('F')
    MSG_TYPE_DATA = ord('D')
    MSG_TYPE_INFO = ord('I')
    MSG_TYPE_PARAMETER = ord('P')
    MSG_TYPE_ADD_LOGGED_MSG = ord('A')
    MSG_TYPE_REMOVE_LOGGED_MSG = ord('R')
    MSG_TYPE_SYNC = ord('S')
    MSG_TYPE_DROPOUT = ord('O')
    MSG_TYPE_LOGGING = ord('L')

    UNPACK_TYPES = {
            'int8_t'   : [ 'b', 1, np.int8 ],
            'uint8_t'  : [ 'B', 1, np.uint8 ],
            'int16_t'  : [ 'h', 2, np.int16 ],
            'uint16_t' : [ 'H', 2, np.uint16 ],
            'int32_t'  : [ 'i', 4, np.int32 ],
            'uint32_t' : [ 'I', 4, np.uint32 ],
            'int64_t'  : [ 'q', 8, np.int64 ],
            'uint64_t' : [ 'Q', 8, np.uint64 ],
            'float'    : [ 'f', 4, np.float32 ],
            'double'   : [ 'd', 8, np.float64 ],
            'bool'     : [ '?', 1, np.int8 ],
            'char'     : [ 'c', 1, np.int8 ]
            }


    """ parsed data """
    start_timestamp = 0 # timestamp of file start
    last_timestamp = 0 # timestam of last message
    msg_info_dict = {} # dict of all information messages
    initial_parameters = {} # dict of all initially set parameters (key=param name)
    changed_parameters = [] # list of all changed parameters (tuple of (timestamp, name, value))
    message_formats = {} # dict with key=format name, value = MessageFormat object
    logged_messages = [] # array of MessageLogging objects
    dropouts = [] # list of MessageDropout objects
    data_list = [] # extracted data: list of Data objects

    class Data:
        def __init__(self, message_add_logged_obj):
            self.multi_id = message_add_logged_obj.multi_id
            self.name = message_add_logged_obj.message_name
            self.field_data = message_add_logged_obj.field_data
            self.timestamp_idx = message_add_logged_obj.timestamp_idx
            # convert to numpy arrays
            self.data = {} # dict of key=field name, value=numpy array of data
            data_tuples = message_add_logged_obj.data_tuples
            num_data_points = len(data_tuples)
            for i in range(len(self.field_data)):
                dtype = ULog.UNPACK_TYPES[self.field_data[i].type_str][2]
                data_array = np.fromiter([x[i] for x in data_tuples], dtype)
                self.data[self.field_data[i].field_name] = data_array



    subscriptions = {} # dict of key=msg_id, value=MessageAddLogged


    """ Representations of the messages from the log file """

    class MessageHeader:
        def __init__(self, data):
            self.msg_size,self.msg_type = struct.unpack('<HB', data)

    class MessageInfo:
        def __init__(self, data, header):
            key_len, = struct.unpack('<B', data[0])
            type_key = parseString(data[1:1+key_len])
            self.type,self.key=type_key.split(' ')
            if (self.type.startswith('char[')): # it's a string
                self.value = parseString(data[1+key_len:])
            elif (self.type in ULog.UNPACK_TYPES):
                unpack_type = ULog.UNPACK_TYPES[self.type]
                self.value, = struct.unpack('<'+unpack_type[0], data[1+key_len:])
            else: # probably an array (or non-basic type)
                self.value = data[1+key_len:]

    class MessageFormat:
        def __init__(self, data, header):
            format_arr = parseString(data).split(':')
            self.name = format_arr[0]
            types_str = format_arr[1].split(';')
            self.fields = [] # list of tuples (type, array_size, name)
            for t in types_str:
                if len(t) > 0:
                    self.fields.append(self.extractType(t))

        def extractType(self, field_str):
            field_str_split = field_str.split(' ')
            type_str = field_str_split[0]
            name_str = field_str_split[1]
            a_pos = type_str.find('[')
            if (a_pos == -1):
                array_size = 1
                type_name = type_str
            else:
                b_pos = type_str.find(']')
                array_size = int(type_str[a_pos+1:b_pos])
                type_name = type_str[:a_pos]
            return type_name, array_size, name_str
            
    class MessageLogging:
        def __init__(self, data, header):
            self.log_level, = struct.unpack('<B', data[0])
            self.timestamp, = struct.unpack('<Q', data[1:9])
            self.message = parseString(data[9:])

        def logLevelStr(self):
            if (self.log_level == ord('0')): return 'EMERG'
            if (self.log_level == ord('1')): return 'ALERT'
            if (self.log_level == ord('2')): return 'CRIT'
            if (self.log_level == ord('3')): return 'ERR'
            if (self.log_level == ord('4')): return 'WARNING'
            if (self.log_level == ord('5')): return 'NOTICE'
            if (self.log_level == ord('6')): return 'INFO'
            if (self.log_level == ord('7')): return 'DEBUG'
            return 'UNKNOWN'

    class MessageDropout:
        def __init__(self, data, header, timestamp):
            self.duration, = struct.unpack('<H', data)
            self.timestamp = timestamp

    class FieldData:
        def __init__(self, field_name, type_str):
            self.field_name = field_name
            self.type_str = type_str

    class MessageAddLogged:
        def __init__(self, data, header, message_formats):
            self.multi_id, = struct.unpack('<B', data[0])
            self.msg_id, = struct.unpack('<H', data[1:3])
            self.message_name = parseString(data[3:])
            self.field_data = [] # list of FieldData
            self.timestamp_idx = -1
            self.parseFormat(message_formats)

            self.data_tuples = [] # list of data tuples, format given by field_data
            self.unpack_str = '<'
            for field in self.field_data:
                unpack_type = ULog.UNPACK_TYPES[field.type_str]
                self.unpack_str += unpack_type[0]

        def parseFormat(self, message_formats):
            self.parseNestedType('', self.message_name, message_formats)

            # remove padding fields at the end
            while (len(self.field_data) > 0 and
                    self.field_data[-1].field_name.startswith('_padding')):
                self.field_data.pop()

        def parseNestedType(self, prefix_str, type_name, message_formats):
            # we flatten nested types
            message_format = message_formats[type_name]
            for (type_name, array_size, field_name) in message_format.fields:
                if type_name in ULog.UNPACK_TYPES:
                    if (array_size > 1):
                        for i in range(array_size):
                            self.field_data.append(ULog.FieldData(
                                prefix_str+field_name+'['+str(i)+']', type_name))
                    else:
                        self.field_data.append(ULog.FieldData(prefix_str+field_name, type_name))
                    if (prefix_str+field_name == 'timestamp'):
                        self.timestamp_idx = len(self.field_data) - 1
                else: # nested type
                    if (array_size > 1):
                        for i in range(array_size):
                            self.parseNestedType(prefix_str+field_name+'['+str(i)+'].',
                                    type_name, message_formats)
                    else:
                        self.parseNestedType(prefix_str+field_name+'.',
                                type_name, message_formats)

    class MessageData:
        def __init__(self, data, header, subscriptions):
            msg_id, = struct.unpack('<H', data[:2])
            if msg_id in subscriptions:
                subscription = subscriptions[msg_id]
                # read the data: all at once to a tuple
                subscription.data_tuples.append(struct.unpack(subscription.unpack_str,
                    data[2:]))
                self.timestamp = subscription.data_tuples[-1][subscription.timestamp_idx]
            else:
                self.timestamp = 0


    def __init__(self, file_name, message_name_filter_list=None):
        """
        Initialize the object & load the file

        @param message_name_filter_list: list of strings, to only load messages
               with the given names.
        """
        self.loadFile(file_name, message_name_filter_list)

    def loadFile(self, file_name, message_name_filter_list):
        """ load and parse an ULog file into memory """
        self.file_name = file_name
        self.file_handle = open(file_name, "rb")

        # parse the whole file
        self.readFileHeader()
        self.last_timestamp = self.start_timestamp
        self.readFileDefinitions()
        self.readFileData(message_name_filter_list)


    def readFileHeader(self):
        header_data = self.file_handle.read(16)
        if (len(header_data)) != 16:
            raise Exception("Invalid file format (Header too short)")
        if (header_data[:7] != self.HEADER_BYTES):
            raise Exception("Invalid file format (Failed to parse header)")
        if (header_data[7] != '\x00'):
            print("Warning: unknown file version. Will attempt to read it anyway")

        # read timestamp
        self.start_timestamp, = struct.unpack('<Q', header_data[8:])

    def readFileDefinitions(self):
        while(True):
            data = self.file_handle.read(3)
            header = self.MessageHeader(data)
            data = self.file_handle.read(header.msg_size)
            if (header.msg_type == self.MSG_TYPE_INFO):
                msg_info = self.MessageInfo(data, header)
                self.msg_info_dict[msg_info.key] = msg_info.value
            elif (header.msg_type == self.MSG_TYPE_FORMAT):
                msg_format = self.MessageFormat(data, header)
                self.message_formats[msg_format.name] = msg_format
            elif (header.msg_type == self.MSG_TYPE_PARAMETER):
                msg_info = self.MessageInfo(data, header)
                self.initial_parameters[msg_info.key] = msg_info.value
            elif (header.msg_type == self.MSG_TYPE_ADD_LOGGED_MSG or
                    header.msg_type == self.MSG_TYPE_LOGGING):
                self.file_handle.seek(-(3+header.msg_size), 1)
                break # end of section
            #else: skip

    def readFileData(self, message_name_filter_list):
        try:
            while(True):
                data = self.file_handle.read(3)
                header = self.MessageHeader(data)
                data = self.file_handle.read(header.msg_size)
                if (header.msg_type == self.MSG_TYPE_PARAMETER):
                    msg_info = self.MessageInfo(data, header)
                    self.changed_parameters.append((self.last_timestamp,
                        msg_info.key, msg_info.value))
                elif (header.msg_type == self.MSG_TYPE_ADD_LOGGED_MSG):
                    msg_add_logged = self.MessageAddLogged(data, header,
                            self.message_formats)
                    if message_name_filter_list == None or \
                        msg_add_logged.message_name in message_name_filter_list:
                        self.subscriptions[msg_add_logged.msg_id] = msg_add_logged
                elif (header.msg_type == self.MSG_TYPE_LOGGING):
                    msg_logging = self.MessageLogging(data, header)
                    self.logged_messages.append(msg_logging)
                elif (header.msg_type == self.MSG_TYPE_DATA):
                    msg_data = self.MessageData(data, header,
                            self.subscriptions)
                    if msg_data.timestamp != 0:
                        self.last_timestamp = msg_data.timestamp
                elif (header.msg_type == self.MSG_TYPE_DROPOUT):
                    msg_dropout = self.MessageDropout(data, header,
                            self.last_timestamp)
                    self.dropouts.append(msg_dropout)
                #else: skip
        except struct.error:
            pass #we read past the end of the file

        # convert into final representation
        while self.subscriptions:
            key, value = self.subscriptions.popitem()
            data_item = ULog.Data(value)
            if len(data_item.data['timestamp']) > 0: # only add if we have data
                self.data_list.append(data_item)

