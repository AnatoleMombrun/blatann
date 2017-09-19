from enum import Enum, IntEnum
import logging
from pc_ble_driver_py.exceptions import NordicSemiException
from blatann.nrf.nrf_dll_load import driver
import blatann.nrf.nrf_driver_types as util


logger = logging.getLogger(__name__)


class BLEGapAdvType(Enum):
    connectable_undirected = driver.BLE_GAP_ADV_TYPE_ADV_IND
    connectable_directed = driver.BLE_GAP_ADV_TYPE_ADV_DIRECT_IND
    scanable_undirected = driver.BLE_GAP_ADV_TYPE_ADV_SCAN_IND
    non_connectable_undirected = driver.BLE_GAP_ADV_TYPE_ADV_NONCONN_IND


class BLEGapRoles(Enum):
    invalid = driver.BLE_GAP_ROLE_INVALID
    periph = driver.BLE_GAP_ROLE_PERIPH
    central = driver.BLE_GAP_ROLE_CENTRAL


class BLEGapTimeoutSrc(Enum):
    advertising = driver.BLE_GAP_TIMEOUT_SRC_ADVERTISING
    security_req = driver.BLE_GAP_TIMEOUT_SRC_SECURITY_REQUEST
    scan = driver.BLE_GAP_TIMEOUT_SRC_SCAN
    conn = driver.BLE_GAP_TIMEOUT_SRC_CONN


class BLEGapIoCaps(IntEnum):
    DISPLAY_ONLY = driver.BLE_GAP_IO_CAPS_DISPLAY_ONLY
    DISPLAY_YESNO = driver.BLE_GAP_IO_CAPS_DISPLAY_YESNO
    KEYBOARD_ONLY = driver.BLE_GAP_IO_CAPS_KEYBOARD_ONLY
    NONE = driver.BLE_GAP_IO_CAPS_NONE
    KEYBOARD_DISPLAY = driver.BLE_GAP_IO_CAPS_KEYBOARD_DISPLAY


class BLEGapAuthKeyType(IntEnum):
    NONE = driver.BLE_GAP_AUTH_KEY_TYPE_NONE
    PASSKEY = driver.BLE_GAP_AUTH_KEY_TYPE_PASSKEY
    OOB = driver.BLE_GAP_AUTH_KEY_TYPE_OOB


class BLEGapAdvParams(object):
    def __init__(self, interval_ms, timeout_s):
        self.interval_ms = interval_ms
        self.timeout_s = timeout_s

    def to_c(self):
        adv_params = driver.ble_gap_adv_params_t()
        adv_params.type = BLEGapAdvType.connectable_undirected.value
        adv_params.p_peer_addr = None  # Undirected advertisement.
        adv_params.fp = driver.BLE_GAP_ADV_FP_ANY
        adv_params.p_whitelist = None
        adv_params.interval = util.msec_to_units(self.interval_ms,
                                                 util.UNIT_0_625_MS)
        adv_params.timeout = self.timeout_s

        return adv_params


class BLEGapScanParams(object):
    def __init__(self, interval_ms, window_ms, timeout_s):
        self.interval_ms = interval_ms
        self.window_ms = window_ms
        self.timeout_s = timeout_s

    def to_c(self):
        scan_params = driver.ble_gap_scan_params_t()
        scan_params.active = True
        scan_params.selective = False
        scan_params.p_whitelist = None
        scan_params.interval = util.msec_to_units(self.interval_ms,
                                                  util.UNIT_0_625_MS)
        scan_params.window = util.msec_to_units(self.window_ms,
                                                util.UNIT_0_625_MS)
        scan_params.timeout = self.timeout_s

        return scan_params


class BLEGapConnParams(object):
    def __init__(self, min_conn_interval_ms, max_conn_interval_ms, conn_sup_timeout_ms, slave_latency):
        self.min_conn_interval_ms = min_conn_interval_ms
        self.max_conn_interval_ms = max_conn_interval_ms
        self.conn_sup_timeout_ms = conn_sup_timeout_ms
        self.slave_latency = slave_latency

    @classmethod
    def from_c(cls, conn_params):
        return cls(min_conn_interval_ms=util.units_to_msec(conn_params.min_conn_interval,
                                                           util.UNIT_1_25_MS),
                   max_conn_interval_ms=util.units_to_msec(conn_params.max_conn_interval,
                                                           util.UNIT_1_25_MS),
                   conn_sup_timeout_ms=util.units_to_msec(conn_params.conn_sup_timeout,
                                                          util.UNIT_10_MS),
                   slave_latency=conn_params.slave_latency)

    def to_c(self):
        conn_params = driver.ble_gap_conn_params_t()
        conn_params.min_conn_interval = util.msec_to_units(self.min_conn_interval_ms,
                                                           util.UNIT_1_25_MS)
        conn_params.max_conn_interval = util.msec_to_units(self.max_conn_interval_ms,
                                                           util.UNIT_1_25_MS)
        conn_params.conn_sup_timeout = util.msec_to_units(self.conn_sup_timeout_ms,
                                                          util.UNIT_10_MS)
        conn_params.slave_latency = self.slave_latency

        return conn_params

    def __str__(self):
        return "{}(interval: [{!r}-{!r}] ms, timeout: {!r} ms, latency: {!r})".format(self.__class__.__name__,
                                                                                      self.min_conn_interval_ms,
                                                                                      self.max_conn_interval_ms,
                                                                                      self.conn_sup_timeout_ms,
                                                                                      self.slave_latency)


class BLEGapAddr(object):
    class Types(Enum):
        public = driver.BLE_GAP_ADDR_TYPE_PUBLIC
        random_static = driver.BLE_GAP_ADDR_TYPE_RANDOM_STATIC
        random_private_resolvable = driver.BLE_GAP_ADDR_TYPE_RANDOM_PRIVATE_RESOLVABLE
        random_private_non_resolvable = driver.BLE_GAP_ADDR_TYPE_RANDOM_PRIVATE_NON_RESOLVABLE

    def __init__(self, addr_type, addr):
        assert isinstance(addr_type, BLEGapAddr.Types), 'Invalid argument type'
        self.addr_type = addr_type
        self.addr = addr

    @classmethod
    def from_c(cls, addr):
        addr_list = util.uint8_array_to_list(addr.addr, driver.BLE_GAP_ADDR_LEN)
        addr_list.reverse()
        return cls(addr_type=BLEGapAddr.Types(addr.addr_type),
                   addr=addr_list)

    @classmethod
    def from_string(cls, addr_string):
        addr, addr_flag = addr_string.split(',')
        addr_list = [int(i, 16) for i in addr.split(':')]

        # print addr_string, addr_list[-1], addr_list[-1] & 0b11000000, 0b11000000
        # print addr_string, addr_list[-1], addr_list[-1] & 0b10000000, 0b10000000
        if addr_flag in ['p', 'public']:
            addr_type = BLEGapAddr.Types.public
        elif (addr_list[0] & 0b11000000) == 0b00000000:
            addr_type = BLEGapAddr.Types.random_private_non_resolvable
        elif (addr_list[0] & 0b11000000) == 0b01000000:
            addr_type = BLEGapAddr.Types.random_private_resolvable
        elif (addr_list[0] & 0b11000000) == 0b11000000:
            addr_type = BLEGapAddr.Types.random_static
        else:
            raise ValueError("Provided random address do not follow rules")  # TODO: Improve error message

        return cls(addr_type, addr_list)

    def to_c(self):
        addr_array = util.list_to_uint8_array(self.addr[::-1])
        addr = driver.ble_gap_addr_t()
        addr.addr_type = self.addr_type.value
        addr.addr = addr_array.cast()
        return addr

    def get_addr_type_str(self):
        if self.addr_type == BLEGapAddr.Types.public:
            return 'public'
        elif self.addr_type == BLEGapAddr.Types.random_private_non_resolvable:
            return 'nonres'
        elif self.addr_type == BLEGapAddr.Types.random_private_resolvable:
            return 'res'
        elif self.addr_type == BLEGapAddr.Types.random_static:
            return 'static'
        else:
            return 'err {0:02b}'.format((self.AddressLtlEnd[-1] >> 6) & 0b11)

    def get_addr_str(self):
        return '"{}" ({:> 6})'.format(self, self.get_addr_type_str())

    def __eq__(self, other):
        if not isinstance(other, BLEGapAddr):
            other = BLEGapAddr.from_string(str(other))
        return str(self) == str(other)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return str(self)

    def get_addr_flag(self):
        return 'p' if self.addr_type == BLEGapAddr.Types.public else 'r'

    def __str__(self):
        return '{},{}'.format(':'.join(['%02X' % i for i in self.addr]), self.get_addr_flag())

    def __repr__(self):
        return "{}.from_string({})".format(self.__class__.__name__, str(self))


class BLEAdvData(object):
    class Types(Enum):
        flags = driver.BLE_GAP_AD_TYPE_FLAGS
        service_16bit_uuid_more_available = driver.BLE_GAP_AD_TYPE_16BIT_SERVICE_UUID_MORE_AVAILABLE
        service_16bit_uuid_complete = driver.BLE_GAP_AD_TYPE_16BIT_SERVICE_UUID_COMPLETE
        service_32bit_uuid_more_available = driver.BLE_GAP_AD_TYPE_32BIT_SERVICE_UUID_MORE_AVAILABLE
        service_32bit_uuid_complete = driver.BLE_GAP_AD_TYPE_32BIT_SERVICE_UUID_COMPLETE
        service_128bit_uuid_more_available = driver.BLE_GAP_AD_TYPE_128BIT_SERVICE_UUID_MORE_AVAILABLE
        service_128bit_uuid_complete = driver.BLE_GAP_AD_TYPE_128BIT_SERVICE_UUID_COMPLETE
        short_local_name = driver.BLE_GAP_AD_TYPE_SHORT_LOCAL_NAME
        complete_local_name = driver.BLE_GAP_AD_TYPE_COMPLETE_LOCAL_NAME
        tx_power_level = driver.BLE_GAP_AD_TYPE_TX_POWER_LEVEL
        class_of_device = driver.BLE_GAP_AD_TYPE_CLASS_OF_DEVICE
        simple_pairing_hash_c = driver.BLE_GAP_AD_TYPE_SIMPLE_PAIRING_HASH_C
        simple_pairing_randimizer_r = driver.BLE_GAP_AD_TYPE_SIMPLE_PAIRING_RANDOMIZER_R
        security_manager_tk_value = driver.BLE_GAP_AD_TYPE_SECURITY_MANAGER_TK_VALUE
        security_manager_oob_flags = driver.BLE_GAP_AD_TYPE_SECURITY_MANAGER_OOB_FLAGS
        slave_connection_interval_range = driver.BLE_GAP_AD_TYPE_SLAVE_CONNECTION_INTERVAL_RANGE
        solicited_sevice_uuids_16bit = driver.BLE_GAP_AD_TYPE_SOLICITED_SERVICE_UUIDS_16BIT
        solicited_sevice_uuids_128bit = driver.BLE_GAP_AD_TYPE_SOLICITED_SERVICE_UUIDS_128BIT
        service_data = driver.BLE_GAP_AD_TYPE_SERVICE_DATA
        public_target_address = driver.BLE_GAP_AD_TYPE_PUBLIC_TARGET_ADDRESS
        random_target_address = driver.BLE_GAP_AD_TYPE_RANDOM_TARGET_ADDRESS
        appearance = driver.BLE_GAP_AD_TYPE_APPEARANCE
        advertising_interval = driver.BLE_GAP_AD_TYPE_ADVERTISING_INTERVAL
        le_bluetooth_device_address = driver.BLE_GAP_AD_TYPE_LE_BLUETOOTH_DEVICE_ADDRESS
        le_role = driver.BLE_GAP_AD_TYPE_LE_ROLE
        simple_pairng_hash_c256 = driver.BLE_GAP_AD_TYPE_SIMPLE_PAIRING_HASH_C256
        simple_pairng_randomizer_r256 = driver.BLE_GAP_AD_TYPE_SIMPLE_PAIRING_RANDOMIZER_R256
        service_data_32bit_uuid = driver.BLE_GAP_AD_TYPE_SERVICE_DATA_32BIT_UUID
        service_data_128bit_uuid = driver.BLE_GAP_AD_TYPE_SERVICE_DATA_128BIT_UUID
        uri = driver.BLE_GAP_AD_TYPE_URI
        information_3d_data = driver.BLE_GAP_AD_TYPE_3D_INFORMATION_DATA
        manufacturer_specific_data = driver.BLE_GAP_AD_TYPE_MANUFACTURER_SPECIFIC_DATA

    def __init__(self, **kwargs):
        self.records = dict()
        for k in kwargs:
            self.records[BLEAdvData.Types[k]] = kwargs[k]

    def to_c(self):
        data_list = list()
        for k in self.records:
            data_list.append(len(self.records[k]) + 1)  # add type length
            data_list.append(k.value)
            if isinstance(self.records[k], str):
                data_list.extend([ord(c) for c in self.records[k]])

            elif isinstance(self.records[k], list):
                data_list.extend(self.records[k])

            else:
                raise NordicSemiException('Unsupported value type: 0x{:02X}'.format(type(self.records[k])))

        data_len = len(data_list)
        if data_len == 0:
            return data_len, None
        else:
            self.__data_array = util.list_to_uint8_array(data_list)
            return data_len, self.__data_array.cast()

    @classmethod
    def from_c(cls, adv_report_evt):
        ad_list = util.uint8_array_to_list(adv_report_evt.data, adv_report_evt.dlen)
        ble_adv_data = cls()
        index = 0
        while index < len(ad_list):
            ad_len = ad_list[index]
            try:
                ad_type = ad_list[index + 1]
                offset = index + 2
                key = BLEAdvData.Types(ad_type)
                ble_adv_data.records[key] = ad_list[offset: offset + ad_len - 1]
            except ValueError:
                logger.error('Invalid advertising data type: 0x{:02X}'.format(ad_type))
                pass
            except IndexError:
                logger.error('Invalid advertising data: {}'.format(ad_list))
                return ble_adv_data
            index += (ad_len + 1)

        return ble_adv_data