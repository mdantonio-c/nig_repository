(function () {
  "use strict";

  // loggedLandingPage = "logged.study";
  loggedLandingPage = "logged.stats";

  angular.module("web").constant("customRoutes", {
    // JUST A TEST
    // Note: this will automatically check api online as not subchild of 'logged'

    "public.welcome": {
      url: "/welcome",
      views: {
        unlogged: {
          dir: "blueprint",
          templateUrl: "welcome.html",
        },
      },
    },

    "logged.study": {
      url: "/study",
      views: {
        "loggedview@logged": {
          dir: "blueprint",
          templateUrl: "study_list.html",
        },
      },
    },

    "logged.study.datasets": {
      url: "/:s_accession",
      views: {
        "loggedview@logged": {
          dir: "blueprint",
          templateUrl: "study.html",
        },
      },
    },

    "logged.study.datasets.files": {
      url: "/:d_accession",
      views: {
        "loggedview@logged": {
          dir: "blueprint",
          templateUrl: "dataset.html",
        },
      },
    },
    /*
    'logged.specialsearch': {
        url: "/search", 
        views: {
            "loggedview@logged": {
                dir: 'blueprint',
                templateUrl: 'search.html'
            }
        }
    },
*/

    "logged.stats": {
      url: "/stats",
      views: {
        "loggedview@logged": {
          dir: "blueprint",
          templateUrl: "stats.html",
        },
      },
    },

    "logged.admin": {
      url: "/admin",
      views: {
        "loggedview@logged": {
          templateUrl: "admin.html",
        },
      },
    },

    "logged.admin.users": {
      url: "/users",
      views: {
        "admin@logged.admin": {
          templateUrl: "admin.users.html",
        },
      },
    },

    "logged.admin.groups": {
      url: "/groups",
      views: {
        "admin@logged.admin": {
          dir: "blueprint",
          templateUrl: "admin.groups.html",
        },
      },
    },

    "logged.admin.institutes": {
      url: "/institutes",
      views: {
        "admin@logged.admin": {
          dir: "blueprint",
          templateUrl: "admin.institutes.html",
        },
      },
    },

    "logged.admin.queue": {
      url: "/queue",
      views: {
        "admin@logged.admin": {
          dir: "base",
          templateUrl: "admin.queue.html",
        },
      },
    },

    ///////////////
  });
})();
