from aiohttp import web

async def health_check(request):
    return web.Response(text="OK", status=200)

app = web.Application()
app.router.add_get("/", health_check)

if __name__ == "__main__":
    web.run_app(app, port=8080)