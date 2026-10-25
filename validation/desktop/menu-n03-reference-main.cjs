const {app,BrowserWindow}=require('electron');
if(!process.env.MENU_N03_REFERENCE_DIRECTORY||!process.env.MENU_N03_REFERENCE_FILE)throw new Error('经营关注参考目录与文件必须明确');
app.setPath('userData',process.env.MENU_N03_REFERENCE_DIRECTORY);
app.whenReady().then(async()=>{
  const window=new BrowserWindow({show:false,width:1440,height:1024,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
  await window.loadFile(process.env.MENU_N03_REFERENCE_FILE);
});
