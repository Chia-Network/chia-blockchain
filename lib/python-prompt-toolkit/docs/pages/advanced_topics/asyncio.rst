.. _asyncio:

Running on top of the `asyncio` event loop
==========================================

.. note::

    New in prompt_toolkit 3.0. (In prompt_toolkit 2.0 this was possible using a
    work-around).

Prompt_toolkit 3.0 uses asyncio natively. Calling ``Application.run()`` will
automatically run the asyncio event loop.

If however you want to run a prompt_toolkit ``Application`` within an asyncio
environment, you have to call the ``prompt_async`` method, like this:

.. code:: python

    from prompt_toolkit.application import Application

    async def main():
        # Define application.
        application = Application(
            ...
        )

        result = await application.run_async()
        print(result)

    asyncio.get_event_loop().run_until_complete(main())
