from .map_aiter import map_aiter
from .join_aiters import join_aiters


def message_stream_to_event_stream(event_template, message_stream):
    """
    This tweaks each message from message_stream by wrapping it with a dictionary
    populated with the given template, putting the message is at the top
    level under "message".
    """

    template = dict(event_template)

    def adaptor(message):
        event = dict(template)
        event.update(message=message)
        return event

    return map_aiter(adaptor, message_stream)


def rws_to_event_aiter(rws_aiter, reader_to_message_stream):

    def rws_to_reader_event_template_adaptor(rws):
        return rws, rws["reader"]

    def reader_event_template_to_event_stream_adaptor(rws_reader):
        rws, reader = rws_reader
        return message_stream_to_event_stream(rws, reader_to_message_stream(reader))

    def adaptor(rws):
        return reader_event_template_to_event_stream_adaptor(
            rws_to_reader_event_template_adaptor(rws))

    return join_aiters(map_aiter(adaptor, rws_aiter))
