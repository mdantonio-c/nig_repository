import { Component, OnInit } from "@angular/core";
import { ActivatedRoute, Router } from '@angular/router';
import { DataService } from "@app/services/data.service";
import { Study } from "@app/types";
import { NotificationService } from "@rapydo/services/notification";

@Component({
  selector: "nig-study",
  templateUrl: "./study.component.html",
  styleUrls: ["./study.component.css"],
})
export class StudyComponent implements OnInit {

  study: Study;
  active = 1;

  links = [
    { title: 'Datasets', fragment: 'datasets', icon: 'fa-database' },
    { title: 'Stage', fragment: 'stage', icon: 'fa-upload' },
    { title: 'Technical', fragment: 'technical', icon: 'fa-file-alt' },
    { title: 'Samples', fragment: 'samples', icon: 'fa-vials' },
    { title: 'Resources', fragment: 'resources', icon: 'fa-archive' },
    { title: 'Access & Security', fragment: 'access', icon: 'fa-shield-alt' },
  ];

	constructor(
    private dataService: DataService,
    public route: ActivatedRoute,
    private router: Router,
    private notify: NotificationService,
  ) {
    this.study = this.router.getCurrentNavigation().extras.state as Study;
  }

  ngOnInit() {
    const uuid = this.route.snapshot.params.study_uuid;
    if(!uuid){
      this.notify.showError("study_uuid parameter not found");
      return;
    }

    if (!this.study) {
      // console.log(`load study <${uuid}>`);
      this.dataService.getStudy(uuid).subscribe(
        (data) => {
          this.study = data;
        },
        (error) => {
          this.notify.showError(error);
        });
    }
  }

}