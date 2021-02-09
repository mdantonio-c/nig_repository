(function () {
  "use strict";

  angular.module("web").controller("SearchController", SearchController);

  function SearchController($scope, $log, DataService, FormlyService, noty) {
    var self = this;
    self.openFilters = { variants: true };

    DataService.getSearchSchema().then(
      function (out_data) {
        self.model = {};
        self.fields = {};

        for (var section_index in out_data.data) {
          var section = out_data.data[section_index];
          var section_key = section.key;
          var data = FormlyService.json2Form(
            section.sections,
            self.model,
            "SearchController"
          );
          self.fields[section_key] = data.fields;
          // self.model = data.model;

          angular.extend(self.model, data.model);
        }

        noty.extractErrors(out_data, noty.WARNING);
      },
      function (out_data) {
        noty.extractErrors(out_data, noty.ERROR);
      }
    );

    self.getSectionTitle = function (section) {
      var info = {};
      info["title"] = section[0].toUpperCase() + section.substr(1);
      info["tooltip"] = "Filter by " + section + " metadata";

      if (section == "phenotype") {
        info["icon"] = "user";
      } else if (section == "variants") {
        info["icon"] = "random";
      } else if (section == "geographical") {
        info["icon"] = "globe";
      } else if (section == "technical") {
        info["icon"] = "modal-window";
      }

      return info;
    };
    self.querySearch = function (type, query) {
      if (type == "HPO") return self.HPO_querySearch(query);
      else if (type == "main_effect") return self.mainEffect_querySearch(query);
      else {
        $log.error("Type (" + type + ") not found in SearchController");
      }
    };

    self.HPO_querySearch = function (query) {
      return DataService.getHPO(query).then(
        function (out_data) {
          return out_data.data;
        },
        function (out_data) {
          return [];
        }
      );
    };
    self.mainEffect_querySearch = function (query) {
      return DataService.getMainEffect(query).then(
        function (out_data) {
          return out_data.data;
        },
        function (out_data) {
          return [];
        }
      );
    };

    self.search = function () {
      if (!self.form.$valid) return false;

      self.loading = true;
      self.openFilters = {};

      DataService.search(self.model).then(
        function (out_data) {
          self.results = out_data.data;
          self.query_filters = {};
          Object.keys(self.model).forEach(function (key) {
            self.query_filters[key] = self.model[key];
          });
          noty.extractErrors(out_data, noty.WARNING);
          if (self.results.length == 0) {
            self.openFilters = { variants: true };
          }
          self.loading = false;
        },
        function (out_data) {
          noty.extractErrors(out_data, noty.ERROR);
          self.loading = false;
          self.openFilters = { variants: true };
        }
      );
      return 0;
    };
  }
})();
