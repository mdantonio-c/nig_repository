(function () {
  "use strict";

  angular.module("web").filter("arrayTolist", ArrayToList);
  angular.module("web").filter("orderObjectBy", orderObjectBy);
  angular.module("web").filter("getLength", getLength);

  function ArrayToList() {
    return function (value /*, param1, param2, ...param n */) {
      var re = /^\['(.+)'\]$/g;
      var m = re.exec(value);

      if (m) return m[1];
      return value.toString().replace(",", ", ");
    };
  }

  function orderObjectBy() {
    return function (items, field, reverse) {
      var filtered = [];
      angular.forEach(items, function (item) {
        filtered.push(item);
      });
      filtered.sort(function (a, b) {
        return a[field] > b[field] ? 1 : -1;
      });
      if (reverse) filtered.reverse();
      return filtered;
    };
  }

  function getLength() {
    return function (object) {
      return Object.keys(object).length;
      /*
      Another working approach:
      var counter = 0
      angular.forEach(object, function(item) {
        counter++;
      });

      return counter;
      */
    };
  }
})();
