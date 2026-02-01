const { request } = require('../../utils/request');

Page({
  data: {
    code: '',
    shares: '',
    cost: ''
  },
  onInput(e) {
    const key = e.currentTarget.dataset.key;
    this.setData({ [key]: e.detail.value });
  },
  async submit() {
    const { code, shares, cost } = this.data;
    if (!code || !shares || !cost) {
      return wx.showToast({ title: '请填写完整', icon: 'none' });
    }

    wx.showLoading({ title: '提交中...' });
    try {
      await request('/assets/add', 'POST', {
        code, 
        shares: parseFloat(shares), 
        cost: parseFloat(cost)
      });
      wx.hideLoading();
      wx.showToast({ title: '添加成功' });
      
      // 延迟返回，让用户看到成功提示
      setTimeout(() => {
        wx.navigateBack();
      }, 1000);
      
    } catch (e) {
      wx.hideLoading();
      wx.showToast({ title: '添加失败，请检查代码', icon: 'none' });
    }
  }
});