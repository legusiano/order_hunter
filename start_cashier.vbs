' Запускает кассу заказов (cashier.py) без окна. Чтобы стартовала с Windows — положи копию в shell:startup
Set sh = CreateObject("WScript.Shell")
py = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe")
sh.CurrentDirectory = "C:\Users\USER\Desktop\order_hunter"
sh.Run """" & py & """ ""C:\Users\USER\Desktop\order_hunter\cashier.py""", 0, False
