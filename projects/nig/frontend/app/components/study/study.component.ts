import { Component, OnInit } from "@angular/core";
import { ActivatedRoute, Router } from '@angular/router';
import { DataService } from "@app/services/data.service";
import { Study } from "@app/types";
import { NotificationService } from "@rapydo/services/notification";

@Component({
  selector: "nig-study",
  templateUrl: "./study.component.html",
})
export class StudyComponent implements OnInit {

  study: Study;

	constructor(
    private dataService: DataService,
    private activatedRoute: ActivatedRoute,
    private router: Router,
    private notify: NotificationService,
  ) {
    this.study = this.router.getCurrentNavigation().extras.state as Study;
  }

  ngOnInit() {
    const uuid = this.activatedRoute.snapshot.params.study_uuid;
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