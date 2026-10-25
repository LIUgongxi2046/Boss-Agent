const {app,BrowserWindow}=require('electron');
app.whenReady().then(async()=>{
  const window=new BrowserWindow({show:false,width:1440,height:1024,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
  await window.loadFile(process.env.MENU_F01_DESIGN_FILE);
});
