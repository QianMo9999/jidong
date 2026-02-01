const { request } = require('../../utils/request');

Page({
  data: {
    total_assets: '0.00',
    total_day_profit: '0.00',
    funds: []
  },

  onShow() {
    this.fetchData();
  },

  onPullDownRefresh() {
    this.fetchData().then(() => wx.stopPullDownRefresh());
  },

  async fetchData() {
    wx.showNavigationBarLoading();
    try {
      const res = await request('/assets/list');
      this.setData({
        total_assets: res.total_assets.toFixed(2),
        total_day_profit: res.total_day_profit.toFixed(2),
        funds: res.funds
      });
    } catch (e) {
      console.error(e);
    } finally {
      wx.hideNavigationBarLoading();
    }
  },

  goToAdd() {
    wx.navigateTo({ url: '/pages/add-asset/add-asset' });
  }
});