App({
  onLaunch() {
    this.login();
  },
  login() {
    const token = wx.getStorageSync('token');
    if (!token) {
      wx.login({
        success: res => {
          if (res.code) {
            wx.request({
              url: 'http://127.0.0.1:5000/api/auth/wx-login',
              method: 'POST',
              data: { code: res.code },
              success: (authRes) => {
                if (authRes.data.token) {
                  wx.setStorageSync('token', authRes.data.token);
                }
              }
            });
          }
        }
      });
    }
  }
});