import { Component } from "@angular/core";
// import * as moment from "moment";
import { environment } from "@rapydo/../environments/environment";

@Component({
  selector: "customfooter",
  templateUrl: "./custom.footer.html",
})
export class CustomFooterComponent {
  public project: string;
  public version: string;
  // public from_year: number;
  // public to_year: number;

  constructor() {
    let title = environment.projectTitle;
    title = title.replace(/^'/, "");
    title = title.replace(/'$/, "");

    let description = environment.projectDescription;
    description = description.replace(/^'/, "");
    description = description.replace(/'$/, "");

    this.project = `${title}: ${description}`;

    this.version = environment.projectVersion;
    // let m = moment();
    // this.from_year = m.year();
    // this.to_year = m.year();
  }
}
