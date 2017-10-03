from collections import namedtuple
import logging
from blatann.nrf import nrf_types, nrf_events
from blatann import gatt
from blatann.exceptions import InvalidOperationException
from blatann.event_type import EventSource


logger = logging.getLogger(__name__)


_security_mapping = {
    gatt.SecurityLevel.NO_ACCESS: nrf_types.BLEGapSecModeType.NO_ACCESS,
    gatt.SecurityLevel.OPEN: nrf_types.BLEGapSecModeType.OPEN,
    gatt.SecurityLevel.JUST_WORKS: nrf_types.BLEGapSecModeType.ENCRYPTION,
    gatt.SecurityLevel.MITM: nrf_types.BLEGapSecModeType.MITM,
}


class GattsCharacteristicProperties(gatt.CharacteristicProperties):
    def __init__(self, read=True, write=False, notify=False, indicate=False, broadcast=False,
                 write_no_response=False, signed_write=False,
                 security_level=gatt.SecurityLevel.OPEN, max_length=20, variable_length=True):
        super(GattsCharacteristicProperties, self).__init__(read, write, notify, indicate, broadcast,
                                                            write_no_response, signed_write)
        self.security_level = security_level
        self.max_len = max_length
        self.variable_length = variable_length


class GattsCharacteristic(gatt.Characteristic):
    """
    Represents a single characteristic within a service. This class is usually not instantiated directly; it
    is added to a service through GattsService::add_characteristic()
    """
    _QueuedChunk = namedtuple("QueuedChunk", ["offset", "data"])

    def __init__(self, ble_device, peer, uuid, properties, value="", prefer_indications=True):
        """
        :param ble_device:
        :param peer:
        :param uuid:
        :type properties: gatt.GattsCharacteristicProperties
        :param value:
        :param prefer_indications:
        """
        super(GattsCharacteristic, self).__init__(ble_device, peer, uuid, properties)
        self._value = value
        self.prefer_indications = prefer_indications
        # Events
        self._on_write = EventSource("Write Event", logger)
        self._on_read = EventSource("Read Event", logger)
        self._on_sub_change = EventSource("Subscription Change Event", logger)
        # Subscribed events
        self.ble_device.ble_driver.event_subscribe(self._on_gatts_write, nrf_events.GattsEvtWrite)
        self.ble_device.ble_driver.event_subscribe(self._on_rw_auth_request, nrf_events.GattsEvtReadWriteAuthorizeRequest)
        # Internal state tracking stuff
        self._write_queued = False
        self._read_in_process = False
        self._queued_write_chunks = []
        self.peer.on_disconnect.register(self._on_disconnect)

    """
    Public Methods
    """

    def set_value(self, value, notify_client=False):
        """
        Sets the value of the characteristic.

        :param value: The value to set to. Must be an iterable type such as a str, bytearray, or list of uint8 values.
                      Length must be less than the characteristic's max length
        :param notify_client: Flag whether or not to notify the client. If indications and notifications are not set up
                              for the characteristic, will raise an InvalidOperationException
        :raises: InvalidOperationException if value length is too long, or notify client set and characteristic
                 is not notifiable
        """
        if len(value) > self.max_length:
            raise InvalidOperationException("Attempted to set value of {} with length greater than max "
                                            "(got {}, max {})".format(self.uuid, len(value), self.max_length))
        if notify_client and not self.notifiable:
            raise InvalidOperationException("Cannot notify client. "
                                            "{} not set up for notifications or indications".format(self.uuid))

        v = nrf_types.BLEGattsValue(value)
        self.ble_device.ble_driver.ble_gatts_value_set(self.peer.conn_handle, self.value_handle, v)

        if notify_client and self.client_subscribed and not self._read_in_process:
            if self.cccd_state == gatt.SubscriptionState.INDICATION:
                hvx_type = nrf_types.BLEGattHVXType.indication
            else:
                hvx_type = nrf_types.BLEGattHVXType.notification
            hvx_params = nrf_types.BLEGattsHvx(self.value_handle, hvx_type, None)
            self.ble_device.ble_driver.ble_gatts_hvx(self.peer.conn_handle, hvx_params)

        self._value = value

    """
    Properties
    """

    @property
    def max_length(self):
        """
        The max possible the value the characteristic can be set to
        """
        return self._properties.max_len

    @property
    def notifiable(self):
        """
        Gets if the characteristic is set up to asynchonously notify clients via notifications or indications
        """
        return self._properties.indicate or self._properties.notify

    @property
    def value(self):
        """
        Gets the current value of the characteristic

        :rtype: bytearray
        """
        return self._value

    @property
    def client_subscribed(self):
        """
        Gets if the client is currently subscribed (notify or indicate) to this characteristic
        """
        return self.peer and self.cccd_state != gatt.SubscriptionState.NOT_SUBSCRIBED

    """
    Events
    """

    @property
    def on_write(self):
        """
        Event generated whenever a client writes to this characteristic.

        Handler args: (GattsCharacteristic this characteristic, bytearray value written)

        :return: an Event which can have handlers registered to and deregistered from
        :rtype: blatann.event_type.Event
        """
        return self._on_write

    @property
    def on_read(self):
        """
        Event generated whenever a client requests to read from this characteristic. At this point, the application
        may choose to update the value of the characteristic to a new value using set_value.

        A good example of this is a "system time" characteristic which reports the applications system time in seconds.
        Instead of updating this characteristic every second, it can be "lazily" updated only when read from.

        NOTE: if there are multiple handlers subscribed to this and each set the value differently, it may cause
        unintended behavior.

        Handler args: (GattsCharacteristic this characteristic)

        :return: an Event which can have handlers registered to and deregistered from
        :rtype: blatann.event_type.Event
        """
        return self._on_read

    @property
    def on_subscription_change(self):
        """
        Event that is generated whenever a client changes its subscription state of the characteristic
        (notify, indicate, none).

        Handler args: (GattsCharacteristic this characteristic, blatann.gatt.SubscriptionState new state)

        :return: an Event which can have handlers registered to and deregistered from
        :rtype: blatann.event_type.Event
        """
        return self._on_sub_change

    """
    Event Handling
    """

    def _handle_in_characteristic(self, attribute_handle):
        return attribute_handle in [self.value_handle, self.cccd_handle]

    def _execute_queued_write(self, write_op):
        if not self._write_queued:
            return

        self._write_queued = False
        if write_op == nrf_events.BLEGattsWriteOperation.exec_write_req_cancel:
            logger.info("Cancelling write request, char: {}".format(self.uuid))
        else:
            logger.info("Executing write request, char: {}".format(self.uuid))
            # TODO Assume that it was assembled properly. Error handling should go here
            new_value = bytearray()
            for chunk in self._queued_write_chunks:
                new_value += bytearray(chunk.data)
            logger.debug("New value: 0x{}".format(str(new_value).encode("hex")))
            self.ble_device.ble_driver.ble_gatts_value_set(self.peer.conn_handle, self.value_handle,
                                                           nrf_types.BLEGattsValue(new_value))
            self._value = new_value
            self._on_write.notify(self, self.value)
        self._queued_write_chunks = []

    def _on_cccd_write(self, event):
        """
        :type event: nrf_events.GattsEvtWrite
        """
        self.cccd_state = gatt.SubscriptionState.from_buffer(bytearray(event.data))
        self._on_sub_change.notify(self, self.cccd_state)

    def _on_gatts_write(self, driver, event):
        """
        :type event: nrf_events.GattsEvtWrite
        """
        if event.attribute_handle == self.cccd_handle:
            self._on_cccd_write(event)
            return
        elif event.attribute_handle != self.value_handle:
            return
        self._value = bytearray(event.data)
        self._on_write.notify(self, self.value)

    def _on_write_auth_request(self, write_event):
        """
        :type write_event: nrf_events.GattsEvtWrite
        """
        if write_event.write_op in [nrf_events.BLEGattsWriteOperation.exec_write_req_cancel,
                                    nrf_events.BLEGattsWriteOperation.exec_write_req_now]:
            self._execute_queued_write(write_event.write_op)
            # Reply should already be handled in database since this can span multiple characteristics and services
            return

        if not self._handle_in_characteristic(write_event.attribute_handle):
            # Handle is not for this characteristic, do nothing
            return

        # Build out the reply
        params = nrf_types.BLEGattsAuthorizeParams(nrf_types.BLEGattStatusCode.success, True,
                                                   write_event.offset, write_event.data)
        reply = nrf_types.BLEGattsRwAuthorizeReplyParams(write=params)

        # Check that the write length is valid
        if write_event.offset + len(write_event.data) > self._properties.max_len:
            params.gatt_status = nrf_types.BLEGattStatusCode.invalid_att_val_length
            self.ble_device.ble_driver.ble_gatts_rw_authorize_reply(write_event.conn_handle, reply)
        else:
            # Send reply before processing write, in case user sets data in gatts_write handler
            try:
                self.ble_device.ble_driver.ble_gatts_rw_authorize_reply(write_event.conn_handle, reply)
            except Exception as e:
                pass
            if write_event.write_op == nrf_events.BLEGattsWriteOperation.prep_write_req:
                self._write_queued = True
                self._queued_write_chunks.append(self._QueuedChunk(write_event.offset, write_event.data))
            elif write_event.write_op in [nrf_events.BLEGattsWriteOperation.write_req,
                                          nrf_types.BLEGattsWriteOperation.write_cmd]:
                self._on_gatts_write(None, write_event)

        # TODO More logic

    def _on_read_auth_request(self, read_event):
        """
        :type read_event: nrf_events.GattsEvtRead
        """
        if not self._handle_in_characteristic(read_event.attribute_handle):
            # Don't care about handles outside of this characteristic
            return

        params = nrf_types.BLEGattsAuthorizeParams(nrf_types.BLEGattStatusCode.success, False, read_event.offset)
        reply = nrf_types.BLEGattsRwAuthorizeReplyParams(read=params)
        if read_event.offset > len(self.value):
            params.gatt_status = nrf_types.BLEGattStatusCode.invalid_offset
        else:
            self._read_in_process = True
            # If the client is reading from the beginning, notify handlers in case an update needs to be made
            if read_event.offset == 0:
                self._on_read.notify(self)
            self._read_in_process = False

        self.ble_device.ble_driver.ble_gatts_rw_authorize_reply(read_event.conn_handle, reply)

    def _on_rw_auth_request(self, driver, event):
        if not self.peer:
            logger.warning("Got RW request when peer not connected: {}".format(event.conn_handle))
            return
        if event.read:
            self._on_read_auth_request(event.read)
        elif event.write:
            self._on_write_auth_request(event.write)
        else:
            logging.error("auth request was not read or write???")

    def _on_disconnect(self, peer, reason):
        if self.cccd_handle and self.cccd_state != gatt.SubscriptionState.NOT_SUBSCRIBED:
            self.cccd_state = gatt.SubscriptionState.NOT_SUBSCRIBED
            # TODO: Not working goodly
            # self.ble_device.ble_driver.ble_gatts_value_set(nrf_types.BLE_CONN_HANDLE_INVALID, self.cccd_handle,
            #                                                nrf_types.BLEGattsValue(gatt.SubscriptionState.to_buffer(self.cccd_state)))


class GattsService(gatt.Service):
    @property
    def characteristics(self):
        """
        :rtype: list of GattsCharacteristic
        """
        return self._characteristics

    def add_characteristic(self, uuid, properties, initial_value=""):
        """
        :type uuid: blatann.uuid.Uuid
        :type properties: gatt.CharacteristicProperties
        :type initial_value: str or list or bytearray
        :rtype: GattsCharacteristic
        """
        c = GattsCharacteristic(self.ble_device, self.peer, uuid, properties, initial_value)
        # Register UUID
        self.ble_device.uuid_manager.register_uuid(uuid)

        # Create property structure
        props = nrf_types.BLEGattCharacteristicProperties(properties.broadcast, properties.read, False,
                                                          properties.write, properties.notify, properties.indicate,
                                                          False)
        # Create cccd metadata if notify/indicate enabled
        if properties.notify or properties.indicate:
            cccd_metadata = nrf_types.BLEGattsAttrMetadata(read_auth=False, write_auth=False)
        else:
            cccd_metadata = None

        char_md = nrf_types.BLEGattsCharMetadata(props, cccd_metadata=cccd_metadata)
        security = _security_mapping[properties.security_level]
        attr_metadata = nrf_types.BLEGattsAttrMetadata(security, security, properties.variable_length,
                                                       read_auth=True, write_auth=True)
        attribute = nrf_types.BLEGattsAttribute(uuid.nrf_uuid, attr_metadata, properties.max_len, initial_value)

        handles = nrf_types.BLEGattsCharHandles()  # Populated in call
        self.ble_device.ble_driver.ble_gatts_characteristic_add(self.start_handle, char_md, attribute, handles)

        c.value_handle = handles.value_handle
        c.cccd_handle = handles.cccd_handle

        if c.cccd_handle != gatt.BLE_GATT_HANDLE_INVALID:
            self.end_handle = c.cccd_handle
        else:
            self.end_handle = c.value_handle

        self.characteristics.append(c)
        return c


class GattsDatabase(gatt.GattDatabase):
    def __init__(self, ble_device, peer):
        super(GattsDatabase, self).__init__(ble_device, peer)
        self.ble_device.ble_driver.event_subscribe(self._on_rw_auth_request,
                                                   nrf_events.GattsEvtReadWriteAuthorizeRequest)

    @property
    def services(self):
        """
        :rtype: list of GattsService
        """
        return self._services

    def iter_services(self):
        for s in self.services:
            for c in s.characteristics:
                yield c

    def add_service(self, uuid, service_type=gatt.ServiceType.PRIMARY):
        """
        Adds a service to the local database

        :type uuid: blatann.uuid.Uuid
        :type service_type: gatt.ServiceType
        :return: The added and newly created service
        :rtype: GattsService
        """
        # Register UUID
        self.ble_device.uuid_manager.register_uuid(uuid)
        handle = nrf_types.BleGattHandle()
        # Call code to add service to driver
        self.ble_device.ble_driver.ble_gatts_service_add(service_type.value, uuid.nrf_uuid, handle)
        service = GattsService(self.ble_device, self.peer, uuid, service_type, handle.handle)
        service.start_handle = handle.handle
        service.end_handle = handle.handle
        self.services.append(service)
        return service

    def _on_rw_auth_request(self, driver, event):
        if not event.write:
            return
        # execute writes can span multiple services and characteristics. Should only reply at the top-level here
        if event.write.write_op not in [nrf_events.BLEGattsWriteOperation.exec_write_req_now,
                                        nrf_events.BLEGattsWriteOperation.exec_write_req_cancel]:
            return
        params = nrf_types.BLEGattsAuthorizeParams(nrf_types.BLEGattStatusCode.success, False)
        reply = nrf_types.BLEGattsRwAuthorizeReplyParams(write=params)
        self.ble_device.ble_driver.ble_gatts_rw_authorize_reply(event.conn_handle, reply)
