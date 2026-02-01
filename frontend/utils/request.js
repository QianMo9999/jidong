const BASE_URL = 'http://127.0.0.1:5000/api';

const request = (url, method = 'GET', data = {}) => {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync('token');
    wx.request({
      url: BASE_URL + url,
      method: method,
      data: data,
      header: {
        'Content-Type': 'application/json',
        'Authorization': token ? `Bearer ${token}` : ''
      },
      success: (res) => {
        if (res.statusCode === 200) {
          resolve(res.data);
        } else if (res.statusCode === 401) {
          // Token失效，重新登录
          wx.removeStorageSync('token');
          getApp().login();
          reject('Unauthorized');
        } else {
          reject(res.data);
        }
      },
      fail: (err) => reject(err)
    });
  });
};

module.exports = { request };