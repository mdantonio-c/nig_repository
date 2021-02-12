import { NgModule } from "@angular/core";
import { RouterModule, Routes } from "@angular/router";

import { SharedModule } from "@rapydo/shared.module";
import { AuthGuard } from "@rapydo/app.auth.guard";

import { StudiesComponent } from "./components/studies/studies.component";

const routes: Routes = [
  {
    path: "app/studies",
    component: StudiesComponent,
    canActivate: [AuthGuard],
    runGuardsAndResolvers: "always",
  },
  {
    path: "",
    redirectTo: "/app/studies",
    pathMatch: "full",
  },
  {
    path: "app",
    redirectTo: "/app/studies",
    pathMatch: "full",
  },

  /* AngularJS routes */
  /*
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
    'logged.specialsearch': {
        url: "/search", 
        views: {
            "loggedview@logged": {
                dir: 'blueprint',
                templateUrl: 'search.html'
            }
        }
    },
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
    */
];

@NgModule({
  imports: [SharedModule, RouterModule.forChild(routes)],
  declarations: [
    StudiesComponent,
  ],

  providers: [],

  exports: [RouterModule],
})
export class CustomModule {}
