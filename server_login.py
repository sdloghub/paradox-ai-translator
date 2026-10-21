"""Personal server sign-in page. Credentials travel through the SSH tunnel."""
LOGIN_PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>登录 · 翻译工作台</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f7f7f5;color:#242424;font:16px system-ui,sans-serif;display:grid;min-height:100vh;place-items:center;padding:24px}
main{width:100%;max-width:420px;background:white;border:1px solid #ddd;border-radius:12px;padding:32px}h1{font-size:26px;margin-top:0}p{color:#666;line-height:1.6}label{display:block;margin:20px 0 8px}input,button{width:100%;padding:12px;font:inherit;border:1px solid #bbb;border-radius:6px}button{margin-top:24px;background:#303b52;color:white;cursor:pointer}small{display:block;margin-top:20px;color:#666;line-height:1.6}
</style><main><h1>翻译工作台</h1><p role="status">请输入登录信息</p>
<form method="post" action="/api/login">
<label for="username">用户名</label><input id="username" name="username" placeholder="输入管理员用户名" autocomplete="username" required>
<label for="password">密码</label><input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
<button type="submit">登录</button></form><small>登录状态保持 8 小时。刷新页面无需重复登录；服务器重启后需要重新登录。</small></main></html>'''
