const path=require('node:path');
const {app,BrowserWindow}=require('electron');
app.setPath('userData',path.resolve(__dirname,'../.work/menu-n02-reference-profile'));
app.whenReady().then(async()=>{
  const window=new BrowserWindow({show:false,width:1440,height:1024,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
  await window.loadFile(process.env.MENU_N02_DESIGN_FILE);
});
