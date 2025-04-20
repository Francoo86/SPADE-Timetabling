import asyncio

class AsyncioSingleton(type):
    _instances = {}
    _locks = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            if cls not in cls._locks:
                cls._locks[cls] = asyncio.Lock()
            
            cls._instances[cls] = None
            
        return cls._instances[cls] or cls.get_instance(cls, *args, **kwargs)
    
    @classmethod
    async def get_instance(mcs, cls, *args, **kwargs):
        if cls._instances[cls] is None:
            async with cls._locks[cls]:
                if cls._instances[cls] is None:
                    cls._instances[cls] = super(AsyncioSingleton, cls).__call__(*args, **kwargs)
        
        return cls._instances[cls]