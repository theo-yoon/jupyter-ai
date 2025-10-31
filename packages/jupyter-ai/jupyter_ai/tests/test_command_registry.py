import asyncio

import pytest

from jupyter_ai.tools import CommandExecutionRegistry


def test_registry_deduplicates_and_resolves():
    async def scenario():
        registry = CommandExecutionRegistry()

        handle_primary = await registry.begin('key')
        assert handle_primary.owns_execution is True

        handle_duplicate = await registry.begin('key')
        assert handle_duplicate.is_duplicate is True
        assert handle_duplicate.future is handle_primary.future

        await registry.resolve(handle_primary, {'result': 42})

        result = await handle_duplicate.future
        assert result == {'result': 42}

        handle_new = await registry.begin('key')
        assert handle_new.owns_execution is True

    asyncio.run(scenario())


def test_registry_rejects_waiters():
    async def scenario():
        registry = CommandExecutionRegistry()

        handle_primary = await registry.begin('key')
        handle_duplicate = await registry.begin('key')

        exc = RuntimeError('failure')
        await registry.reject(handle_primary, exc)

        with pytest.raises(RuntimeError) as caught:
            await handle_duplicate.future
        assert 'failure' in str(caught.value)

        handle_new = await registry.begin('key')
        assert handle_new.owns_execution is True

    asyncio.run(scenario())
